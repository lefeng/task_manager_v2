"""
WebSocket manager for job-level gRPC stream updates.

Tracks active WebSocket connections keyed by job_uuid so that the gRPC
stream consumer can push live status updates (state, progress, task_statuses)
to the right clients.

Database-level table change events (INSERT/UPDATE/DELETE) are handled
separately by core.event_manager.EventWSManager.
"""

import logging
from collections import defaultdict

from fastapi import WebSocket

from core.event_manager import _send_all

logger = logging.getLogger(__name__)


class JobStatusManager:
    def __init__(self) -> None:
        # job_uuid → set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # clients subscribed to all job updates
        self._global: set[WebSocket] = set()

    async def connect(self, job_uuid: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[job_uuid].add(ws)
        logger.debug(
            "WS connect: job=%s total=%d", job_uuid, len(self._connections[job_uuid])
        )

    def disconnect(self, job_uuid: str, ws: WebSocket) -> None:
        self._connections[job_uuid].discard(ws)
        if not self._connections[job_uuid]:
            del self._connections[job_uuid]
        logger.debug("WS disconnect: job=%s", job_uuid)

    async def connect_global(self, ws: WebSocket) -> None:
        await ws.accept()
        self._global.add(ws)
        logger.debug("WS global connect: total=%d", len(self._global))

    def disconnect_global(self, ws: WebSocket) -> None:
        self._global.discard(ws)
        logger.debug("WS global disconnect: total=%d", len(self._global))

    async def broadcast(self, job_uuid: str, data: dict) -> None:
        """Send data to per-job clients and all global subscribers."""
        job_set = self._connections.get(job_uuid, set())
        for ws in await _send_all(job_set | self._global, data):
            if ws in job_set:
                self.disconnect(job_uuid, ws)
            else:
                self.disconnect_global(ws)


# Singleton — imported by jobs/router.py and core/grpc_client.py
job_status_manager = JobStatusManager()
