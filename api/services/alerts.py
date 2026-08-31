"""
Alert rules.

The rapid-intensification threshold is the standard operational definition -
an increase of at least 30 kt in 24 hours - so it is citable rather than
invented. Making up a threshold invites a question with no good answer.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from cyclops.domain.imd import (CATEGORY_LABEL, RAPID_INTENSIFICATION_KT_24H,
                                category_to_index)


class AlertService:
    def check(self, history: pd.DataFrame) -> list[dict]:
        if history.empty:
            return []
        out = []
        now = history.iloc[-1]

        if len(history) == 1:
            out.append({
                "kind": "detection", "severity": "info",
                "ts": now.iso_time.isoformat(),
                "message": (f"System detected at {now.lat:.1f}N {now.lon:.1f}E — "
                            f"{CATEGORY_LABEL.get(now.imd_category, now.imd_category)}"),
            })

        # Rapid intensification: >= 30 kt in 24 h.
        day_ago = now.iso_time - timedelta(hours=24)
        past = history[history.iso_time <= day_ago]
        if not past.empty:
            delta = float(now.wind_kt_3min) - float(past.iloc[-1].wind_kt_3min)
            if delta >= RAPID_INTENSIFICATION_KT_24H:
                out.append({
                    "kind": "rapid_intensification", "severity": "critical",
                    "ts": now.iso_time.isoformat(),
                    "message": (f"Rapid intensification: +{delta:.0f} kt in 24 h "
                                f"(now {now.wind_kt_3min:.0f} kt, "
                                f"{now.imd_category})"),
                })

        # Category escalation between consecutive fixes.
        if len(history) >= 2:
            prev = history.iloc[-2]
            if category_to_index(now.imd_category) > category_to_index(prev.imd_category):
                out.append({
                    "kind": "category_change", "severity": "warning",
                    "ts": now.iso_time.isoformat(),
                    "message": (f"Intensified to "
                                f"{CATEGORY_LABEL.get(now.imd_category)} "
                                f"({now.wind_kt_3min:.0f} kt)"),
                })

        # Landfall watch. dist2land is an IBTrACS field, so the threshold is
        # against a real distance rather than a guessed coastline.
        if pd.notna(now.dist2land_km) and float(now.dist2land_km) < 150 \
                and float(now.wind_kt_3min) >= 34:
            out.append({
                "kind": "landfall_watch", "severity": "warning",
                "ts": now.iso_time.isoformat(),
                "message": (f"Within {float(now.dist2land_km):.0f} km of land "
                            f"at {now.imd_category} intensity"),
            })
        return out
