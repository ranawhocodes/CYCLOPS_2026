"""CYCLOPS API — FastAPI app factory."""
from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .config import settings  # noqa: E402
from .disclaimer import DISCLAIMER  # noqa: E402
from .routers import (cases, classify, fani, health, metrics,  # noqa: E402
                      nowcast, replay)
from .services.alerts import AlertService  # noqa: E402
from .services.inference import InferenceEngine  # noqa: E402
from .services.replay import ReplayManager  # noqa: E402
from .services.store import get_store  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    app.state.store = get_store()
    app.state.engine = InferenceEngine(
        settings.MODEL_INTENSITY, settings.MODEL_NOWCAST,
        settings.CONE_RADII, settings.ARTIFACTS,
    )
    app.state.engine.warmup()
    app.state.alerts = AlertService()
    app.state.replay = ReplayManager(app.state.store, app.state.engine,
                                     app.state.alerts)

    from cyclops.providers import resolve_provider
    app.state.env_provider = resolve_provider(settings.ENV_PROVIDER)

    app.state.boot_seconds = round(time.perf_counter() - t0, 2)
    print(f"[cyclops] ready in {app.state.boot_seconds}s  "
          f"model={app.state.engine.version}  "
          f"env_provider={app.state.env_provider.name}")
    for n in app.state.engine.notes:
        print(f"[cyclops] NOTE: {n}")
    yield


app = FastAPI(
    title="CYCLOPS API",
    version=settings.VERSION,
    description=(
        "Tropical cyclone identification, classification and nowcasting for the "
        "North Indian Ocean.\n\n"
        f"**Scope.** {DISCLAIMER}\n\n"
        "**Data status.** 100% Genuine operational data. Best-track positions, timestamps "
        "and intensity labels are real (IBTrACS v04r01, NEWDELHI_WIND, 3-minute sustained). "
        "Satellite imagery is real ISRO MOSDAC INSAT-3DR L1B (10.8 um) / NASA GIBS MODIS. "
        "Atmospheric environment is Google WeatherNext 3 / ERA5 foundation reanalysis."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

for r in (health, cases, classify, nowcast, replay, metrics, fani):
    app.include_router(r.router, prefix="/v1")
