"""
Train the fusion intensity model and run the ablation study.

The ablation IS the result. A single accuracy number from a fusion model proves
nothing about fusion; four models trained identically and scored on the same
held-out storms proves whether the extra modalities earned their place.

Reminder, enforced in the output: the imagery here is synthetic, so these
numbers measure whether the pipeline is correct, not whether the system reads
satellites well. Every artefact this writes is stamped SYNTHETIC.
"""
from __future__ import annotations

import json
import time

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset

from ..config import ARTIFACTS, DATA_PROCESSED, MODELS, SEED
from ..domain.imd import CATEGORIES
from ..eval.metrics import intensity_report
from ..models.fusion import CyclopsFusion, modality_dropout
from ..models.heads import huber_weighted

ABLATIONS = {
    "fusion":   {"use_wind": True,  "use_env": True},
    "ir_env":   {"use_wind": False, "use_env": True},
    "ir_wind":  {"use_wind": True,  "use_env": False},
    "ir_only":  {"use_wind": False, "use_env": False},
}


def device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


_KEYS = ("ir", "wind", "wind_present", "env", "y_kt", "y_cat", "y_tnum",
         "d_centre", "sid", "iso_time")


def load_all_splits():
    """
    Load every split in ONE pass over the file.

    Calling np.load once per split reads the whole 700 MB archive three times
    and holds three full copies of the image array while slicing — enough to
    push a 16 GB laptop into swap and get the process killed. One pass, slice
    three ways, drop the source.
    """
    with np.load(DATA_PROCESSED / "vision_dataset.npz", allow_pickle=False) as d:
        split = d["split"]
        masks = {n: split == n for n in ("train", "val", "test")}
        out = {n: {} for n in masks}
        for k in _KEYS:
            arr = d[k]
            for n, m in masks.items():
                v = arr[m]
                # Stored as float16 to halve the file; the model runs in float32.
                out[n][k] = v.astype(np.float32) if k in ("ir", "wind") else v
            del arr
    return out["train"], out["val"], out["test"]


def make_loader(s, batch=32, shuffle=False):
    return DataLoader(
        TensorDataset(
            torch.from_numpy(s["ir"]), torch.from_numpy(s["wind"]),
            torch.from_numpy(s["wind_present"]), torch.from_numpy(s["env"]),
            torch.from_numpy(s["y_kt"]), torch.from_numpy(s["y_tnum"]),
            torch.from_numpy(s["d_centre"]),
        ),
        batch_size=batch, shuffle=shuffle, num_workers=0, drop_last=False,
    )


@torch.no_grad()
def predict(model, loader, dev, use_wind=True, use_env=True):
    model.eval()
    P, T = [], []
    for ir, wind, pres, env, y, _, _ in loader:
        ir, wind, env = ir.to(dev), wind.to(dev), env.to(dev)
        pres = pres.to(dev) if use_wind else torch.zeros_like(pres).to(dev)
        if not use_env:
            env = torch.zeros_like(env)
        P.append(model(ir, wind, pres, env)["wind_kt"].cpu().numpy())
        T.append(y.numpy())
    return np.concatenate(P), np.concatenate(T)


def train_one(name, cfg, tr, va, dev, epochs=14, lr=3e-4, batch=32):
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    model = CyclopsFusion().to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    tl = make_loader(tr, batch, shuffle=True)
    vl = make_loader(va, batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, total_steps=epochs * len(tl), pct_start=0.15)

    best, best_state, patience = float("inf"), None, 0
    t0 = time.perf_counter()
    for ep in range(epochs):
        model.train()
        for ir, wind, pres, env, y, tnum, dc in tl:
            ir, wind, env = ir.to(dev), wind.to(dev), env.to(dev)
            y, tnum, dc = y.to(dev), tnum.to(dev), dc.to(dev)
            pres = pres.to(dev)
            if cfg["use_wind"]:
                pres = modality_dropout(pres, p_drop=0.3)
            else:
                pres = torch.zeros_like(pres)
            if not cfg["use_env"]:
                env = torch.zeros_like(env)

            out = model(ir, wind, pres, env)
            loss = (huber_weighted(out["wind_kt"], y)
                    + 0.3 * torch.nn.functional.mse_loss(out["t_number"], tnum)
                    # Centre-fixing is trained jointly. It shares the trunk, so
                    # it also acts as an auxiliary task that forces the encoder
                    # to localise the storm rather than reading global texture.
                    + 5.0 * torch.nn.functional.mse_loss(out["d_centre"], dc))

            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step()

        p, t = predict(model, vl, dev, cfg["use_wind"], cfg["use_env"])
        rmse = float(np.sqrt(((p - t) ** 2).mean()))
        print(f"  [{name}] ep {ep+1:02d}/{epochs}  val RMSE {rmse:6.2f} kt")
        if rmse < best - 0.05:
            best, patience = rmse, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience += 1
            if patience >= 4:
                print(f"  [{name}] early stop at epoch {ep+1}")
                break

    if best_state:
        model.load_state_dict(best_state)
    print(f"  [{name}] best val RMSE {best:.2f} kt  ({time.perf_counter()-t0:.0f}s)")
    return model, best


@torch.no_grad()
def centre_error_px(model, loader, dev):
    """Median centre-fix error, converted to km at 4 km/px."""
    from ..config import IR_SIZE, PATCH_KM
    model.eval()
    errs = []
    for ir, wind, pres, env, _, _, dc in loader:
        out = model(ir.to(dev), wind.to(dev), pres.to(dev), env.to(dev))
        d = (out["d_centre"].cpu() - dc) * (IR_SIZE / 2)
        errs.append((d.norm(dim=1) * (PATCH_KM / IR_SIZE)).numpy())
    e = np.concatenate(errs)
    return {"median_km": float(np.median(e)), "p90_km": float(np.percentile(e, 90)),
            "n": int(len(e))}


def main(epochs: int = 14):
    dev = device()
    tr, va, te = load_all_splits()
    print(f"device={dev}  train={len(tr['y_kt'])}  val={len(va['y_kt'])}  "
          f"test={len(te['y_kt'])}  test storms={len(set(te['sid']))}")

    tel = make_loader(te)
    results, best_model = {}, None
    for name, cfg in ABLATIONS.items():
        print(f"\n--- {name} ---")
        model, _ = train_one(name, cfg, tr, va, dev, epochs=epochs)
        p, t = predict(model, tel, dev, cfg["use_wind"], cfg["use_env"])
        results[name] = intensity_report(p, t)
        if name == "fusion":
            best_model = model

    base = results["ir_only"]["rmse_kt"]
    print("\n" + "=" * 72)
    print("ABLATION — identical held-out storms, split by season")
    print(f"test: {len(set(te['sid']))} storms, {results['fusion']['n']} samples")
    print("=" * 72)
    print(f"{'variant':<10} {'RMSE kt':>9} {'MAE kt':>8} {'bias':>7} "
          f"{'cat acc':>9} {'within-1':>9} {'vs IR-only':>11}")
    print("-" * 72)
    for name in ABLATIONS:
        r = results[name]
        rel = (base - r["rmse_kt"]) / base
        print(f"{name:<10} {r['rmse_kt']:>9.2f} {r['mae_kt']:>8.2f} "
              f"{r['bias_kt']:>7.2f} {r['cat_acc']:>8.1%} {r['within_one']:>9.1%} "
              f"{rel:>10.1%}")
    print("=" * 72)

    r = results["fusion"]
    print("\nPer-category MAE (fusion), with sample counts:")
    for c in CATEGORIES:
        if c in r["per_cat_mae"]:
            print(f"  {c:<5} n={r['per_cat_n'][c]:>4}  MAE {r['per_cat_mae'][c]:>6.2f} kt")

    ce = centre_error_px(best_model, tel, dev)
    print(f"\nCentre-fix error: median {ce['median_km']:.1f} km, "
          f"p90 {ce['p90_km']:.1f} km  (n={ce['n']})")

    MODELS.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": best_model.state_dict(),
                "arch": "CyclopsFusion",
                "trained_on": "SYNTHETIC imagery + REAL IBTrACS labels"},
               MODELS / "cyclops_intensity.pt")

    payload = {
        "DATA_STATUS": "SYNTHETIC IMAGERY — pipeline validation, not satellite skill",
        "labels": "REAL — IBTrACS NEWDELHI_WIND, 3-min sustained",
        "split_policy": "by_season; storm IDs disjoint (asserted)",
        "test_storms": len(set(te["sid"])),
        "epochs": epochs,
        "ablation": results,
        "fusion_gain_vs_ir_only": (base - results["fusion"]["rmse_kt"]) / base,
        "centre_fix": ce,
    }
    (ARTIFACTS / "metrics_intensity.json").write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {MODELS/'cyclops_intensity.pt'}")
    print(f"wrote {ARTIFACTS/'metrics_intensity.json'}")
    return payload


if __name__ == "__main__":
    import sys
    main(epochs=int(sys.argv[1]) if len(sys.argv) > 1 else 14)
