"""
Export the fusion model to ONNX and verify numerical parity.

Two reasons this matters beyond tidiness. ONNX Runtime on CPU is typically 2-4x
faster than PyTorch CPU for a model this size, which is what the demo laptop
runs on. And the API image can then install onnxruntime instead of torch, which
takes it from roughly 2.5 GB to under 500 MB and makes cold start fast enough
that `docker compose up` finishes inside the five-minute target.

Never ship an artefact that has not been numerically verified against the
PyTorch model. Silent divergence means the demo shows different numbers from the
report, and nothing tells you.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from ..config import IR_SIZE, MODELS, WIND_SIZE
from ..models.fusion import CyclopsFusion
from ..preprocess import ENV_DIM


def export(ckpt: Path | None = None, out: Path | None = None) -> Path:
    ckpt = Path(ckpt or MODELS / "cyclops_intensity.pt")
    out = Path(out or MODELS / "cyclops_intensity.onnx")

    blob = torch.load(ckpt, map_location="cpu", weights_only=False)
    model = CyclopsFusion()
    model.load_state_dict(blob["state_dict"])
    model.eval()

    dummy = (torch.randn(1, 3, IR_SIZE, IR_SIZE), torch.randn(1, 3, WIND_SIZE, WIND_SIZE),
             torch.ones(1), torch.randn(1, ENV_DIM))

    class Wrapped(torch.nn.Module):
        """ONNX export needs tuple output, not a dict."""
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, ir, wind, wind_present, env):
            o = self.m(ir, wind, wind_present, env)
            return o["wind_kt"], o["t_number"], o["det_logit"], o["d_centre"]

    # external_data=False keeps the weights inside the .onnx. The default in
    # torch 2.9+ writes them to a sidecar `.onnx.data`, which is a quiet way to
    # ship a broken artefact: copy the .onnx alone and it loads, then fails at
    # the first inference. One file, no footgun.
    kwargs = dict(
        input_names=["ir", "wind", "wind_present", "env"],
        output_names=["wind_kt", "t_number", "det_logit", "d_centre"],
        dynamic_axes={k: {0: "batch"} for k in
                      ("ir", "wind", "wind_present", "env", "wind_kt")},
        opset_version=17,
    )
    for sidecar in out.parent.glob(out.name + ".data"):
        sidecar.unlink()
    try:
        torch.onnx.export(Wrapped(model), dummy, str(out),
                          external_data=False, **kwargs)
    except TypeError:
        # Older torch: no external_data flag, and no sidecar behaviour either.
        torch.onnx.export(Wrapped(model), dummy, str(out), **kwargs)

    stray = list(out.parent.glob(out.name + ".data"))
    if stray:
        raise AssertionError(
            f"weights were written to a sidecar ({stray[0].name}) instead of "
            f"being embedded — the .onnx alone would be an unusable artefact")
    print(f"wrote {out}  ({out.stat().st_size / 1e6:.1f} MB, self-contained)")
    verify_parity(model, out)
    return out


def verify_parity(model, onnx_path: Path, tol: float = 1e-3) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed — parity NOT verified. "
              "`pip install onnxruntime` before shipping this artefact.")
        return

    torch.manual_seed(0)
    ir = torch.randn(4, 3, IR_SIZE, IR_SIZE)
    wind = torch.randn(4, 3, WIND_SIZE, WIND_SIZE)
    pres = torch.tensor([1.0, 0.0, 1.0, 0.0])
    env = torch.randn(4, ENV_DIM)

    with torch.no_grad():
        ref = model(ir, wind, pres, env)["wind_kt"].numpy()

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    got = sess.run(["wind_kt"], {
        "ir": ir.numpy(), "wind": wind.numpy(),
        "wind_present": pres.numpy(), "env": env.numpy()})[0]

    diff = float(np.abs(ref - got).max())
    if diff > tol:
        raise AssertionError(f"ONNX divergence: max diff {diff:.5f} kt (tol {tol})")
    print(f"ONNX parity verified — max diff {diff:.2e} kt over 4 samples "
          f"(with and without the wind branch)")


if __name__ == "__main__":
    export()
