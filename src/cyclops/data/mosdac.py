"""
MOSDAC client — INSAT-3D / 3DR / 3DS imagery from ISRO.

This is the production data path for the North Indian Ocean, and the fix for the
ceiling measured in docs/FINDING-eye-detection.md. That analysis found IR
centre-fixing could not beat motion extrapolation because its two dominant error
terms both come from MODIS being polar-orbiting:

    4 km nearest-neighbour centring                ~4-6 km
    +/-30 min ESTIMATED overpass time x ~12 kt     ~11 km

INSAT-3DR removes both. It is geostationary, so imagery arrives every 30 minutes
with a PUBLISHED acquisition timestamp rather than one inferred from an
equator-crossing time. Over Cyclone Fani's lifetime MOSDAC holds 1,947 3DR L1B
granules against the 18 usable MODIS day passes this project has been using.

ACCESS MODEL
------------
Search is open. `search()` needs no account and works right now.

Download requires a MOSDAC account. Register once at https://mosdac.gov.in/signup/
then export credentials into the environment:

    export MOSDAC_USERNAME='...'
    export MOSDAC_PASSWORD='...'

Credentials are read from the environment only. They are never written to disk,
never logged, and never committed — `download()` raises with instructions rather
than prompting, so nothing can capture them by accident.

Endpoints below were taken from MOSDAC's own published client
(https://www.mosdac.gov.in/software/mdapi.zip, documented at
https://mosdac.gov.in/downloadapi-manual). This module reimplements the same
calls rather than executing that script.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import DATA_RAW

SEARCH_URL = "https://mosdac.gov.in/apios/datasets.json"
TOKEN_URL = "https://mosdac.gov.in/download_api/gettoken"
DOWNLOAD_URL = "https://mosdac.gov.in/download_api/download"
REFRESH_URL = "https://mosdac.gov.in/download_api/refresh-token"
SIGNUP_URL = "https://mosdac.gov.in/signup/"

CACHE = DATA_RAW / "insat"
CACHE.mkdir(parents=True, exist_ok=True)

# Level-1B standard imager products. 3D is the original INSAT-3D, 3DR the
# follow-on, 3S the newest. 3DR has the densest 2019-2023 archive, so it is the
# default for the case studies.
DATASETS = {
    "3D": "3DIMG_L1B_STD",
    "3DR": "3RIMG_L1B_STD",
    "3S": "3SIMG_L1B_STD",
}

# INSAT imager channels. TIR-1 is the 10.8 um window channel — the Dvorak band,
# and the direct counterpart of the MODIS Band 31 data used so far.
CHANNELS = {
    "TIR1": "10.8 um thermal infrared (Dvorak window channel)",
    "TIR2": "12.0 um thermal infrared",
    "WV": "6.8 um water vapour",
    "MIR": "3.9 um mid infrared",
    "VIS": "0.65 um visible",
    "SWIR": "1.625 um shortwave infrared",
}


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS via certifi — the python.org macOS build is not wired to the
    system keychain, so urllib otherwise fails against valid hosts."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


class MosdacAuthError(RuntimeError):
    """Raised when a download is attempted without usable credentials."""


@dataclass
class Granule:
    """One INSAT product file as returned by the catalogue."""
    identifier: str
    granule_id: str
    observed_at: datetime
    summary: str
    size_mb: float | None
    enclosure: str

    @property
    def satellite(self) -> str:
        return self.identifier[:5]

    def local_path(self) -> Path:
        return CACHE / self.identifier


def _get(url: str, params: dict | None = None, timeout: int = 60) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v})}"
    req = urllib.request.Request(url, headers={"User-Agent": "CYCLOPS/0.4 (SIH 2026)"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
        return json.loads(r.read())


def search(dataset: str = "3DR", start: str | None = None, end: str | None = None,
           bbox: tuple[float, float, float, float] | None = None,
           count: int | None = None, timeout: int = 60) -> dict:
    """
    Query the MOSDAC catalogue. No account required.

    `bbox` is (west, south, east, north) in degrees. Returns the raw OpenSearch
    response, including `totalResults` and `totalSizeMB`, so a caller can size a
    download before committing to it.
    """
    ds = DATASETS.get(dataset.upper(), dataset)
    params = {"datasetId": ds}
    if start:
        params["startTime"] = start
    if end:
        params["endTime"] = end
    if count:
        params["count"] = str(count)
    if bbox:
        params["boundingBox"] = ",".join(str(v) for v in bbox)
    return _get(SEARCH_URL, params, timeout=timeout)


def granules(dataset: str = "3DR", start: str | None = None, end: str | None = None,
             bbox=None, count: int | None = None) -> list[Granule]:
    """Search, and parse the entries into Granule records."""
    res = search(dataset, start, end, bbox, count)
    out = []
    for e in res.get("entries", []):
        try:
            ts = datetime.fromisoformat(e["updated"].replace("Z", "+00:00"))
        except Exception:
            continue
        out.append(Granule(
            identifier=e.get("identifier", ""), granule_id=str(e.get("id", "")),
            observed_at=ts, summary=e.get("summary", ""),
            size_mb=e.get("sizeMB"), enclosure=e.get("enclosureLink", ""),
        ))
    return sorted(out, key=lambda g: g.observed_at)


def credentials() -> tuple[str, str]:
    """
    Read MOSDAC credentials from the environment.

    Environment only, by design. Nothing prompts, so a password cannot be
    captured into a transcript, a shell history file or a config committed by
    accident.
    """
    u = os.environ.get("MOSDAC_USERNAME", "").strip()
    p = os.environ.get("MOSDAC_PASSWORD", "")
    if not u or not p:
        raise MosdacAuthError(
            "MOSDAC credentials are not set, so downloads are unavailable "
            "(search still works).\n\n"
            f"  1. Register once at {SIGNUP_URL}\n"
            "  2. export MOSDAC_USERNAME='your-username-or-email'\n"
            "     export MOSDAC_PASSWORD='your-password'\n"
            "  3. re-run\n\n"
            "Credentials are read from the environment only — never written to "
            "disk, logged, or committed."
        )
    return u, p


def has_credentials() -> bool:
    try:
        credentials()
        return True
    except MosdacAuthError:
        return False


def get_token(timeout: int = 60) -> dict:
    """Exchange credentials for an access token. Requires an account."""
    u, p = credentials()
    body = json.dumps({"username": u, "password": p}).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "CYCLOPS/0.4 (SIH 2026)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # Deliberately does not echo the request body, so a bad password can
        # never end up in a log or a traceback.
        raise MosdacAuthError(
            f"MOSDAC rejected the credentials (HTTP {e.code}). Check "
            f"MOSDAC_USERNAME / MOSDAC_PASSWORD, and that the account is "
            f"activated at {SIGNUP_URL}."
        ) from None


def download(granule: Granule, token: str | None = None,
             timeout: int = 900) -> Path:
    """
    Fetch one granule to the local cache. Requires an account.

    Files are large — 3DR L1B averages ~300 MB — so callers should thin the
    granule list by cadence before calling this in a loop, and check
    `estimate_download()` first.
    """
    dest = granule.local_path()
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    if token is None:
        token = get_token().get("access_token", "")
    if not token:
        raise MosdacAuthError("no access token returned by MOSDAC")

    body = json.dumps({"gId": granule.granule_id}).encode()
    req = urllib.request.Request(
        DOWNLOAD_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}",
                 "User-Agent": "CYCLOPS/0.4 (SIH 2026)"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r, \
            open(tmp, "wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)
    tmp.rename(dest)
    return dest


def estimate_download(dataset: str = "3DR", start: str | None = None,
                      end: str | None = None, every_minutes: int = 180) -> dict:
    """
    Size a download before committing to it.

    3DR granules average ~300 MB, so a full storm window is hundreds of
    gigabytes. `every_minutes` thins the list to a workable cadence.

    The native cadence is MEASURED from the window rather than assumed. INSAT-3DR
    is nominally half-hourly for full disk, but the archive also carries
    rapid-scan sector products, so the real spacing over a storm window is closer
    to 8 minutes. Assuming 30 would under-count the thinned set by ~4x.
    """
    from datetime import datetime as _dt
    res = search(dataset, start, end, count=1)
    total = int(res.get("totalResults", 0))
    size_mb = float(res.get("totalSizeMB", 0.0))
    per = size_mb / total if total else 0.0

    span_min = 0.0
    if start and end:
        span_min = ((_dt.fromisoformat(end) - _dt.fromisoformat(start)).days + 1) * 1440
    native_min = (span_min / total) if (total and span_min) else float("nan")

    keep = min(total, max(1, int(span_min / every_minutes))) if (total and span_min) else 0
    return {
        "native_cadence_min": round(native_min, 1) if native_min == native_min else None,
        "dataset": DATASETS.get(dataset.upper(), dataset),
        "total_granules": total,
        "total_size_gb": round(size_mb / 1024, 1),
        "mb_per_granule": round(per, 1),
        "thinned_to_every_minutes": every_minutes,
        "thinned_granules": keep,
        "thinned_size_gb": round(keep * per / 1024, 1),
    }
