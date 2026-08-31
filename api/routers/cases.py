from fastapi import APIRouter, HTTPException, Request, Response

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
async def case_frame(case_id: str, ts: str, request: Request):
    """Rendered infrared frame as a PNG."""
    st = request.app.state
    try:
        scene = st.store.scene(case_id, parse_iso(ts))
    except KeyError:
        raise HTTPException(404, f"no frame for {case_id} at {ts}")
    png = st.engine.frame_png(scene["tensors"]["ir"][0])
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600",
                             "X-Data-Status": "SYNTHETIC"})
