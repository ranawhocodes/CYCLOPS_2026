"""
INSAT access CLI.

  python -m cyclops.data.insat_cli status
  python -m cyclops.data.insat_cli search --sat 3DR --start 2019-04-25 --end 2019-05-05
  python -m cyclops.data.insat_cli plan   --start 2019-04-25 --end 2019-05-05 --every 180
  python -m cyclops.data.insat_cli fetch  --start 2019-05-02 --end 2019-05-02 --every 180 --limit 4

`status`, `search` and `plan` need no account. `fetch` needs one; it refuses with
instructions rather than prompting.
"""
from __future__ import annotations

import argparse
import sys

from . import mosdac as M


# Probe dates spanning the three satellites' service eras. A satellite that
# returns nothing for one date has simply not launched yet or has been retired,
# which is coverage rather than a failure — reporting it as FAIL was misleading.
PROBE_DATES = [("2019-05-02", "Fani"), ("2023-05-13", "Mocha"), ("2024-06-01", "recent")]


def cmd_status(_args) -> int:
    print("MOSDAC / INSAT access status")
    print("=" * 66)
    print(f"  {'':5s}{'dataset':17s}" + "".join(f"{lbl:>14s}" for _, lbl in PROBE_DATES))
    reachable = False
    for sat in ("3D", "3DR", "3S"):
        cells = []
        for d, _ in PROBE_DATES:
            try:
                r = M.search(sat, d, d, count=1)
                cells.append(f"{r['totalResults']:>10} gran")
                reachable = True
            except Exception:
                cells.append(f"{'--':>14s}")
        print(f"  {sat:5s}{M.DATASETS[sat]:17s}" + "".join(cells))
    print()
    print("  '--' means that satellite was not in service on that date, "
          "not an error.")
    print("  The catalogue also lags roughly a month behind real time.")
    ok = reachable
    has = M.has_credentials()
    print(f"\n  credentials  {'PRESENT' if has else 'NOT SET'}"
          f"   (MOSDAC_USERNAME / MOSDAC_PASSWORD)")
    print(f"  downloads    {'available' if has else 'UNAVAILABLE — search only'}")
    if not has:
        print(f"\n  To enable downloads:")
        print(f"    1. register once at {M.SIGNUP_URL}")
        print(f"    2. export MOSDAC_USERNAME='...' MOSDAC_PASSWORD='...'")
        print(f"    3. re-run  `make insat-status`")
    return 0 if ok else 1


def cmd_search(a) -> int:
    g = M.granules(a.sat, a.start, a.end, count=a.limit)
    r = M.search(a.sat, a.start, a.end, count=1)
    print(f"{M.DATASETS.get(a.sat.upper(), a.sat)}  {a.start} .. {a.end}")
    print(f"  totalResults {r['totalResults']:,}   totalSize {r['totalSizeMB']/1024:.1f} GB")
    for x in g[: a.limit or 10]:
        print(f"  {x.observed_at:%Y-%m-%d %H:%M}Z  {x.identifier}  id={x.granule_id}")
    return 0


def cmd_plan(a) -> int:
    e = M.estimate_download(a.sat, a.start, a.end, a.every)
    print(f"{e['dataset']}  {a.start} .. {a.end}")
    print(f"  native cadence      {e['native_cadence_min']} min")
    print(f"  full archive        {e['total_granules']:,} granules, {e['total_size_gb']} GB")
    print(f"  thinned to {a.every:>4} min  {e['thinned_granules']:,} granules, "
          f"{e['thinned_size_gb']} GB")
    print(f"  per granule         ~{e['mb_per_granule']} MB")
    return 0


def cmd_fetch(a) -> int:
    if not M.has_credentials():
        print(M.credentials.__doc__ or "")
        try:
            M.credentials()
        except M.MosdacAuthError as err:
            print(err)
        return 2

    g = M.granules(a.sat, a.start, a.end, count=a.limit or 50)
    # Thin to the requested cadence so a loop cannot accidentally pull hundreds
    # of gigabytes.
    keep, last = [], None
    for x in g:
        if last is None or (x.observed_at - last).total_seconds() >= a.every * 60:
            keep.append(x); last = x.observed_at
    if a.limit:
        keep = keep[: a.limit]

    print(f"downloading {len(keep)} granules (~{len(keep) * 297 / 1024:.1f} GB)")
    tok = M.get_token().get("access_token", "")
    for i, x in enumerate(keep, 1):
        try:
            p = M.download(x, token=tok)
            print(f"  [{i}/{len(keep)}] {x.identifier}  ->  {p} "
                  f"({p.stat().st_size/1e6:.0f} MB)")
        except Exception as e:
            print(f"  [{i}/{len(keep)}] {x.identifier}  FAILED: {type(e).__name__}: {e}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="insat_cli", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    for name, fn in (("search", cmd_search), ("plan", cmd_plan), ("fetch", cmd_fetch)):
        p = sub.add_parser(name)
        p.add_argument("--sat", default="3DR", choices=list(M.DATASETS))
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True)
        p.add_argument("--every", type=int, default=180,
                       help="minutes between kept granules")
        p.add_argument("--limit", type=int, default=None)
        p.set_defaults(fn=fn)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
