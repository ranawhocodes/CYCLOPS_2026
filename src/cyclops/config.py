"""Single source of truth for paths and constants. Nothing else hard-codes a path."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("CYCLOPS_ROOT", Path(__file__).resolve().parents[2]))

DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_CASES = ROOT / "data" / "cases"
MODELS = ROOT / "models"
ARTIFACTS = ROOT / "artifacts"

for _p in (DATA_RAW, DATA_PROCESSED, DATA_CASES, MODELS, ARTIFACTS):
    _p.mkdir(parents=True, exist_ok=True)

IBTRACS_NI_URL = (
    "https://www.ncei.noaa.gov/data/"
    "international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/access/csv/ibtracs.NI.list.v04r01.csv"
)
IBTRACS_NI_CSV = DATA_RAW / "ibtracs.NI.list.v04r01.csv"

# Storm-centred patch geometry. These four numbers define the tensor contract
# shared by the training pipeline and the API; changing one without retraining
# is how training-serving skew happens.
# MVP runs at 128 px (8 km/px over a 1024 km patch) so the whole ablation
# trains in minutes on a laptop. The TRD target is 256; raising it is this one
# line plus a rebuild, and nothing downstream hard-codes the number.
IR_SIZE = int(__import__("os").environ.get("CYCLOPS_IR_SIZE", 128))
WIND_SIZE = 64         # pixels per side of the resampled scatterometer patch
PATCH_KM = 1024.0      # physical extent of the IR patch (4 km/px at 256 px)
IR_CHANNELS = 3        # TIR-1 brightness temp, WV brightness temp, BD-enhanced

# Brightness-temperature normalisation range, in kelvin. Cloud tops in a deep
# tropical cyclone reach ~180 K; warm ocean surface in the clear is ~305 K.
BT_MIN = 180.0
BT_MAX = 310.0

SEED = 1337
FORECAST_LEADS_H = (6, 12, 18, 24)
CONE_PERCENTILE = 67   # NHC convention: circle enclosing two-thirds of errors
