from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ._timeparse import parse_iso

router = APIRouter(tags=["inference"])


class ClassifyRequest(BaseModel):
    case_id: str
    timestamp: str
    include_cam: bool = True


@router.post("/classify")
async def classify(req: ClassifyRequest, request: Request):
    """
    Intensity estimate with a Grad-CAM overlay and full provenance.

    Every response carries an interval, a provenance block and a model version.
    There is deliberately no endpoint returning a bare point estimate.
    """
    st = request.app.state
    try:
        scene = st.store.scene(req.case_id, parse_iso(req.timestamp))
    except KeyError as e:
        raise HTTPException(404, str(e))

    t = scene["tensors"]
    out = st.engine.classify(t["ir"], t["wind"], t["wind_present"], t["env"],
                             include_cam=req.include_cam,
                             category_hint=scene["row"].imd_category)
    out["provenance"] = scene["provenance"]
    out["centre"] = {"lat": float(scene["row"].lat), "lon": float(scene["row"].lon)}
    out["truth"] = {"wind_kt": float(scene["row"].wind_kt_3min),
                    "imd_category": scene["row"].imd_category,
                    "source": scene["row"].wind_source}
    return out
