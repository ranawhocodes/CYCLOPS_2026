import sys
sys.path.insert(0, "d:/CYCLOPS/src")
sys.path.insert(0, "d:/CYCLOPS")
from api.services.store import CaseStore

store = CaseStore()
track = store.track("2019116N02090")
print(f"Using scene source: {store.scene_source.name}")
print(f"Granules indexed: {getattr(store.scene_source, 'n_granules', 0)}")

for i in [0, 1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 28, 30, 31, 33, 35]:
    row = track.iloc[i]
    try:
        res = store.scene("2019116N02090", row.iso_time)
        ir_p = res["provenance"]["ir"]
        sc = res["scene"]
        tir1 = sc["tir1_k"]
        print(f"Frame {i:2d} ({row.iso_time}) lat={row.lat:5.1f}, lon={row.lon:5.1f} | min_c={sc['min_c']:6.1f} C, shape={tir1.shape}, range=[{tir1.min():.1f}K, {tir1.max():.1f}K], src={ir_p['source']}")
    except Exception as e:
        print(f"Frame {i:2d} ERROR: {e}")
