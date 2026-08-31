import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ._timeparse import parse_iso

router = APIRouter(tags=["replay"])


class StartRequest(BaseModel):
    speed: float = 120.0


@router.post("/replay/{case_id}/start")
async def start(case_id: str, req: StartRequest, request: Request):
    try:
        s = await request.app.state.replay.start(case_id, req.speed)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return s.state()


@router.post("/replay/{session_id}/pause")
async def pause(session_id: str, request: Request):
    s = _need(request, session_id)
    s.paused = True
    return s.state()


@router.post("/replay/{session_id}/resume")
async def resume(session_id: str, request: Request):
    s = _need(request, session_id)
    s.paused = False
    return s.state()


@router.post("/replay/{session_id}/seek/{idx}")
async def seek(session_id: str, idx: int, request: Request):
    s = _need(request, session_id)
    s.idx = max(0, min(idx, len(s.timestamps) - 1))
    return s.state()


@router.post("/replay/{session_id}/speed/{speed}")
async def set_speed(session_id: str, speed: float, request: Request):
    s = _need(request, session_id)
    s.speed = max(1.0, min(speed, 2000.0))
    return s.state()


@router.delete("/replay/{session_id}")
async def stop(session_id: str, request: Request):
    request.app.state.replay.sessions.pop(session_id, None)
    return {"stopped": session_id}


@router.get("/replay/{session_id}/at/{ts}")
async def at(session_id: str, ts: str, request: Request):
    """Full payload at an arbitrary storm-clock instant. Used when scrubbing."""
    s = _need(request, session_id)
    return request.app.state.replay.compute_at(s.case_id, parse_iso(ts))


def _need(request: Request, session_id: str):
    s = request.app.state.replay.get(session_id)
    if not s:
        raise HTTPException(404, f"unknown replay session {session_id}")
    return s


@router.websocket("/live")
async def live(ws: WebSocket, session_id: str):
    await ws.accept()
    s = ws.app.state.replay.get(session_id)
    if not s:
        await ws.close(code=4004, reason="Unknown session")
        return

    s.subscribers.add(ws)
    hb = asyncio.create_task(_heartbeat(ws))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hb.cancel()
        s.subscribers.discard(ws)


async def _heartbeat(ws: WebSocket, every: int = 15):
    """
    Venue networks and proxies kill idle WebSockets after 30-60 s. Three lines
    here prevent the live panel going dead during a long Q&A pause.
    """
    try:
        while True:
            await asyncio.sleep(every)
            await ws.send_json({"type": "heartbeat",
                                "ts": datetime.now(timezone.utc).isoformat()})
    except Exception:
        pass
