from fastapi import APIRouter, HTTPException, Request, Response

from cyclops.domain.lifecycle import STAGES, annotate, summarise
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
    if w.get("u10") is None:
        return {"available": False,
                "reason": "no analysed wind field at this time",
                "centre": {"lat": float(row.lat), "lon": float(row.lon)}}

    # Analysed field for the flow layer; `coverage` still reports what the
    # scatterometer actually saw, and the provenance panel says which is which.
    grid = wind_grid_payload(w["u10"], w["v10"], w["mask"],
                             float(row.lat), float(row.lon), analysed=True,
                             observed_coverage=w.get("coverage", 0.0))
    grid["available"] = True
    grid["observed"] = bool(w.get("mask_obs") is not None)
    grid["source"] = (scene["provenance"]["wind"] or {}).get("source", "unknown")
    grid["age_min"] = (scene["provenance"]["wind"] or {}).get("age_min")
    grid["centre"] = {"lat": float(row.lat), "lon": float(row.lon)}
    return grid


@router.get("/cases/{case_id}/lifecycle")
async def case_lifecycle(case_id: str, request: Request):
    """
    The storm's life split into named stages, and which capability each exercises.

    Identification, classification and prediction are not three separate demos —
    they are three things a forecaster does at different points in one storm's
    life. This is what lets the console say which one is being shown.
    """
    d = request.app.state.store.track(case_id)
    if d.empty:
        raise HTTPException(404, f"no track for case {case_id}")
    ann = annotate(d)
    return {
        "case_id": case_id,
        "stages": summarise(d),
        "definitions": {k: {"label": v.label, "task": v.task, "detail": v.detail}
                        for k, v in STAGES.items()},
        "per_fix": [
            {"ts": r.iso_time.isoformat(), "stage": r.stage,
             "wind_kt": round(float(r.wind_kt_3min), 1),
             "imd_category": r.imd_category,
             "d24_kt": (round(float(r.d24_kt), 1)
                        if r.d24_kt == r.d24_kt else None)}
            for r in ann.itertuples()
        ],
    }
