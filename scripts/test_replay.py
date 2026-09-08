import sys
sys.path.insert(0, "d:/CYCLOPS/src")
sys.path.insert(0, "d:/CYCLOPS")
from api.services.store import CaseStore
from api.services.inference import InferenceEngine
from api.services.alerts import AlertService
from api.services.replay import ReplayManager
from api.config import settings

store = CaseStore()
engine = InferenceEngine(
    settings.MODEL_INTENSITY, settings.MODEL_NOWCAST,
    settings.CONE_RADII, settings.ARTIFACTS,
)
engine.warmup()
alerts = AlertService()
replay = ReplayManager(store, engine, alerts)

track = store.track("2019116N02090")
print(f"Total track points: {len(track)}")

for i in [0, 1, 3, 7, 11, 15, 19, 23, 27, 30, 35]:
    ts = track.iloc[i].iso_time.to_pydatetime()
    res = replay.compute_at("2019116N02090", ts)
    c = res["classify"]
    n = res["nowcast"]
    f24 = n["forecasts"][-1] if n["forecasts"] else {}
    pos = f24.get("position", {})
    w24 = f24.get("wind_kt", "N/A")
    print(f"Frame {i:2d} ({ts}) -> Est Wind: {c['wind_kt']:.1f} kt, Pred Cat: {c['imd_category']}, Truth: {res['truth_now']['wind_kt']} kt ({res['truth_now']['imd_category']}), IR Source: {c['provenance']['ir']['source']}")
    print(f"       Nowcast 24h lead: pos=({pos.get('lat')}, {pos.get('lon')}), wind: {w24} kt")
