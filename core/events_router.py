"""
Events router.

WebSocket:
  WS  /api/v2/events/ws  — DB-level table change stream via PostgreSQL LISTEN/NOTIFY.
                            Covers all monitored tables (jobs, blueprints).
                            Child-table changes bubble up to their parent topic.

Message format:
    {"topic": "jobs"|"blueprints", "event": "insert"|"update"|"delete", "data": {...}}

data fields by topic:
  jobs       insert/update — uuid, sequence_number, state
  blueprints insert/update — uuid, executor, command, description
  either     delete        — uuid only (row is already gone)
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.event_manager import event_manager

router = APIRouter()


@router.websocket("/ws")
async def events_ws(ws: WebSocket):
    await event_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        event_manager.disconnect(ws)
