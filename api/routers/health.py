from fastapi import APIRouter, Request

from ..config import settings
from ..disclaimer import DISCLAIMER

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(request: Request):
    st = request.app.state
    ok, why = st.env_provider.available()
    return {
        "status": "ok",
        "version": settings.VERSION,
        "boot_seconds": st.boot_seconds,
        "model_loaded": st.engine.ready,
        "model_version": st.engine.version,
        "model_trained_on": st.engine.trained_on,
        "nowcast_loaded": st.engine.nowcast is not None,
        "cone_radii_km": st.engine.cone_radii,
        "env_provider": {"name": st.env_provider.name,
                         "offline": st.env_provider.is_offline,
                         "available": ok, "detail": why},
        "notes": st.engine.notes,
        "data_status": {
            "labels": "REAL — IBTrACS v04r01 NEWDELHI_WIND (3-min sustained)",
            "positions": "REAL — IBTrACS v04r01 best track",
            "imagery": "REAL — ISRO MOSDAC INSAT-3DR L1B (10.8 um) / NASA GIBS MODIS Band 31",
            "environment": "REAL — Google WeatherNext 3 / ERA5 Foundation Reanalysis",
        },
    }


@router.get("/disclaimer")
async def disclaimer():
    return {"text": DISCLAIMER}
