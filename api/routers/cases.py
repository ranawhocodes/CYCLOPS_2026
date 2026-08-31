from fastapi import APIRouter, HTTPException, Request, Response

from cyclops.geo import wind_grid_payload

from ._timeparse import parse_iso

router = APIRouter(tags=["cases"])


@router.get("/cases")
async def list_cases(request: Request):
    return request.app.state.store.cases()


@router.get("/cases/{case_id}/track")
async def case_track(case_id: str, request: Request, until: str | None = None):
    """
    Observed best track, optionally truncated at `until`.

    `until` is the replay causality boundary and is applied in the store's query,
    not here - so the console cannot accidentally reveal the future by omitting
    it, and a refactor cannot silently drop it.
    """
    store = request.app.state.store
    ts = parse_iso(until)
    d = store.track(case_id, until=ts)
    if d.empty:
        raise HTTPException(404, f"no track for case {case_id}")
    return {
        "case_id": case_id,
        "until": until,
        "source": "IBTrACS v04r01 (NEWDELHI 3-min sustained where available)",
        "observed": [
            {"ts": r.iso_time.isoformat(), "lat": round(float(r.lat), 3),
             "lon": round(float(r.lon), 3),
             "wind_kt": round(float(r.wind_kt_3min), 1),
             "pres_hpa": (round(float(r.pres_hpa), 1)
                          if r.pres_hpa == r.pres_hpa else None),
             "imd_category": r.imd_category, "source": r.wind_source}
            for r in d.itertuples()
        ],
    }


@router.get("/cases/{case_id}/frames/{ts}")
async def case_frame(case_id: str, ts: str, request: Request,
                     georef: bool = False):
    """
    Rendered infrared frame as a PNG.

    `georef=1` returns an RGBA version with clear air transparent, for draping
    on the map. The opaque version is what the explainability panel shows,
    because the Grad-CAM overlay needs an opaque base to blend against.
    """
    st = request.app.state
    try:
        scene = st.store.scene(case_id, parse_iso(ts))
    except KeyError:
        raise HTTPException(404, f"no frame for {case_id} at {ts}")
    ir0 = scene["tensors"]["ir"][0]
    png = (st.engine.frame_png_georef(ir0) if georef
           else st.engine.frame_png(ir0))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600",
                             "X-Data-Status": "SYNTHETIC"})


@router.get("/cases/{case_id}/wind/{ts}")
async def case_wind(case_id: str, ts: str, request: Request):
    """
    Scatterometer wind field as a compact grid, for the animated flow layer.

    Cells outside the swath or flagged for rain come back null, so the console
    shows coverage gaps rather than interpolating across them. Returns
    `available: false` when there is no coincident pass -- which is most
    timesteps, and the console says so rather than animating stale motion.
    """
    st = request.app.state
    try:
        scene = st.store.scene(case_id, parse_iso(ts))
    except KeyError:
        raise HTTPException(404, f"no frame for {case_id} at {ts}")

    w = scene["wind"]
    row = scene["row"]
    if w.get("mask") is None:
        return {"available": False,
                "reason": "no coincident scatterometer pass at this time",
                "centre": {"lat": float(row.lat), "lon": float(row.lon)}}

    grid = wind_grid_payload(w["u10"], w["v10"], w["mask"],
                             float(row.lat), float(row.lon))
    grid["available"] = True
    grid["source"] = (scene["provenance"]["wind"] or {}).get("source", "unknown")
    grid["age_min"] = (scene["provenance"]["wind"] or {}).get("age_min")
    grid["centre"] = {"lat": float(row.lat), "lon": float(row.lon)}
    return grid
