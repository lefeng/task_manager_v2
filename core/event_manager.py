"""
WebSocket manager for database-level table change events.

Broadcasts PostgreSQL LISTEN/NOTIFY notifications from the 'db_changes'
channel to all connected WebSocket clients.  Covers all monitored tables
(jobs, blueprints) via a single connection pool.

Clients receive messages in the format:
    {
        "topic": "jobs" | "blueprints",
        "event": "insert" | "update" | "delete",
        "data": { ... }
    }
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


async def _send_all(sockets: set[WebSocket], data: dict) -> set[WebSocket]:
    """Send data to every socket in the set; return the ones that failed."""
    snapshot = list(sockets)
    if not snapshot:
        return set()
    results = await asyncio.gather(
        *[ws.send_json(data) for ws in snapshot],
        return_exceptions=True,
    )
    return {ws for ws, r in zip(snapshot, results) if isinstance(r, Exception)}


class EventWSManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        logger.debug("EventWS connect: total=%d", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.debug("EventWS disconnect: total=%d", len(self._clients))

    async def broadcast(self, data: dict) -> None:
        for ws in await _send_all(self._clients, data):
            self.disconnect(ws)


# Singleton — imported by jobs/events.py and jobs/router.py
event_manager = EventWSManager()
