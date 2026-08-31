"""
Environment field providers.

Track error at 24 hours is dominated by steering-flow uncertainty, not by how
well the model reads the cloud pattern. Our own evaluation shows this directly:
intensity skill over persistence is roughly 33%, while track skill is roughly
11%. The difference is that intensity is largely determined by things visible in
the storm itself, and track is determined by the synoptic flow the storm is
embedded in - which our climatology proxies barely resolve.

So environmental fields are behind an interface rather than hard-coded. Three
implementations, in increasing order of fidelity:

  ClimatologyProvider  - analytic NIO climatology. Offline, zero setup, always
                         works. This is what the demo runs on.
  ERA5Provider         - reanalysis. Correct for historical cases, needs a
                         Copernicus CDS account.
  WeatherNext2Provider - Google DeepMind's AI ensemble forecast. Gives a
                         *forecast* steering flow rather than a climatological
                         average, and gives it as an ensemble, so forecast
                         spread becomes a real input to the uncertainty cone.

Every field carries its own provenance and staleness, so a value from a proxy
can never be presented in the console as if it were an observation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EnvField:
    """One environmental value plus everything needed to judge how much to trust it."""
    name: str
    value: float
    units: str
    source: str
    observed_at: datetime | None = None
    age_minutes: int | None = None
    is_proxy: bool = False           # True => modelled/climatological, not observed
    ensemble_spread: float | None = None


@dataclass
class EnvSnapshot:
    """The environmental state at one storm position and time."""
    lat: float
    lon: float
    valid_at: datetime
    fields: dict[str, EnvField] = field(default_factory=dict)
    provider: str = "unknown"

    def get(self, name: str, default: float = float("nan")) -> float:
        f = self.fields.get(name)
        return f.value if f else default

    @property
    def any_proxy(self) -> bool:
        return any(f.is_proxy for f in self.fields.values())

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "valid_at": self.valid_at.isoformat() if self.valid_at else None,
            "contains_proxy_fields": self.any_proxy,
            "fields": {
                k: {
                    "value": round(v.value, 3),
                    "units": v.units,
                    "source": v.source,
                    "age_minutes": v.age_minutes,
                    "is_proxy": v.is_proxy,
                    "ensemble_spread": (round(v.ensemble_spread, 3)
                                        if v.ensemble_spread is not None else None),
                }
                for k, v in self.fields.items()
            },
        }


# The fields the nowcast consumes. A provider that cannot supply one returns it
# as a proxy rather than omitting it, so the feature vector never changes shape.
REQUIRED_FIELDS = ("sst_c", "shear_kt", "steer_u_kt", "steer_v_kt")


class EnvironmentProvider(ABC):
    """Supplies environmental fields at a storm position and time."""

    name: str = "abstract"
    is_offline: bool = True

    @abstractmethod
    def at(self, lat: float, lon: float, when: datetime) -> EnvSnapshot:
        """Environmental snapshot for one point in space and time."""

    def available(self) -> tuple[bool, str]:
        """(usable_now, human-readable reason). Checked at API startup."""
        return True, "ok"

    def batch(self, points: list[tuple[float, float, datetime]]) -> list[EnvSnapshot]:
        """Override where the backend supports a vectorised query."""
        return [self.at(la, lo, t) for la, lo, t in points]
