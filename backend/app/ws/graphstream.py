"""
/ws/v1/graphstream

Not the general channel for delivering analysed/finished data (that stays
REST, pull-based). Purpose: push live progress during long-running backend
work -- ingestion stage-by-stage, and a single consolidated
"analytics_complete" event for the whole analytics stage (Section 6).

Connect with ?case_id=CASE-1 to watch one case, or ?case_id=* to watch all
(handy for a demo dashboard).
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.ws.manager import ws_manager

router = APIRouter()


@router.websocket("/ws/v1/graphstream")
async def graphstream(websocket: WebSocket, case_id: str = Query(default="*")):
    await ws_manager.connect(case_id, websocket)
    try:
        while True:
            # Client doesn't need to send anything; keep the socket open.
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(case_id, websocket)
