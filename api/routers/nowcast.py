from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ._timeparse import parse_iso

router = APIRouter(tags=["inference"])


class NowcastRequest(BaseModel):
    case_id: str
    t0: str


@router.post("/nowcast")
async def nowcast(req: NowcastRequest, request: Request):
    """6/12/18/24 h track and intensity forecast with an uncertainty cone."""
    st = request.app.state
    history = st.store.track(req.case_id, until=parse_iso(req.t0))
    if history.empty:
        raise HTTPException(404, f"no history for {req.case_id} before {req.t0}")
    return st.engine.forecast(history)
