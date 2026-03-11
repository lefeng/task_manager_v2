"""
WebSocket connection manager.

Tracks active WebSocket connections keyed by job_uuid so that
the gRPC stream consumer can push status updates to the right clients.
"""

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class JobWSManager:
    def __init__(self) -> None:
        # job_uuid → set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, job_uuid: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[job_uuid].add(ws)
        logger.debug("WS connect: job=%s total=%d", job_uuid, len(self._connections[job_uuid]))

    def disconnect(self, job_uuid: str, ws: WebSocket) -> None:
        self._connections[job_uuid].discard(ws)
        if not self._connections[job_uuid]:
            del self._connections[job_uuid]
        logger.debug("WS disconnect: job=%s", job_uuid)

    async def broadcast(self, job_uuid: str, data: dict) -> None:
        """Send data to all clients watching a job. Dead connections are pruned."""
        connections = list(self._connections.get(job_uuid, []))
        if not connections:
            return

        dead: set[WebSocket] = set()
        results = await asyncio.gather(
            *[ws.send_json(data) for ws in connections],
            return_exceptions=True,
        )
        for ws, result in zip(connections, results):
            if isinstance(result, Exception):
                dead.add(ws)

        for ws in dead:
            self.disconnect(job_uuid, ws)

    async def broadcast_all(self, data: dict) -> None:
        """Broadcast to every connected client across all jobs."""
        for job_uuid in list(self._connections.keys()):
            await self.broadcast(job_uuid, data)

    @property
    def active_job_uuids(self) -> list[str]:
        return list(self._connections.keys())


# Singleton — imported by router and grpc_client
manager = JobWSManager()
