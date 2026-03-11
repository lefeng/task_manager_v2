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
        # clients subscribed to all job updates
        self._global: set[WebSocket] = set()

    async def connect(self, job_uuid: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[job_uuid].add(ws)
        logger.debug("WS connect: job=%s total=%d", job_uuid, len(self._connections[job_uuid]))

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
        targets = list(self._connections.get(job_uuid, [])) + list(self._global)
        if not targets:
            return

        dead_job: set[WebSocket] = set()
        dead_global: set[WebSocket] = set()
        job_set = self._connections.get(job_uuid, set())

        results = await asyncio.gather(
            *[ws.send_json(data) for ws in targets],
            return_exceptions=True,
        )
        for ws, result in zip(targets, results):
            if isinstance(result, Exception):
                if ws in job_set:
                    dead_job.add(ws)
                else:
                    dead_global.add(ws)

        for ws in dead_job:
            self.disconnect(job_uuid, ws)
        for ws in dead_global:
            self.disconnect_global(ws)

    async def broadcast_all(self, data: dict) -> None:
        """Broadcast to every connected client across all jobs."""
        for job_uuid in list(self._connections.keys()):
            await self.broadcast(job_uuid, data)

    @property
    def active_job_uuids(self) -> list[str]:
        return list(self._connections.keys())


# Singleton — imported by router and grpc_client
manager = JobWSManager()
