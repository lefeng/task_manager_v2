"""
PostgreSQL LISTEN/NOTIFY listener.

Maintains a single dedicated asyncpg connection (outside the SQLAlchemy pool)
and dispatches change notifications to registered async handler functions.

Usage:
    pg_listener.add_handler(my_async_fn)   # fn(channel, data) → None
    await pg_listener.start(settings.database_url)
    ...
    await pg_listener.stop()

Auto-reconnects on connection loss with a short backoff delay.
"""

import asyncio
import json
import logging
from collections.abc import Coroutine
from typing import Callable

import asyncpg

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5  # seconds
_HEARTBEAT_INTERVAL = 30  # seconds


class PGListener:
    def __init__(self) -> None:
        self._dsn: str = ""
        self._channels: list[str] = []
        self._handlers: list[Callable[..., Coroutine]] = []
        self._conn: asyncpg.Connection | None = None
        self._task: asyncio.Task | None = None

    def add_handler(self, fn: Callable[..., Coroutine]) -> None:
        """Register an async handler: async def fn(channel: str, data: dict)."""
        self._handlers.append(fn)

    def add_channel(self, channel: str) -> None:
        self._channels.append(channel)

    async def start(self, dsn: str) -> None:
        self._dsn = dsn
        self._task = asyncio.create_task(self._run(), name="pg_listener")
        logger.info("PGListener task started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._conn and not self._conn.is_closed():
            await self._conn.close()
        logger.info("PGListener stopped")

    # ── internal ──────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while True:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "PGListener disconnected (%s) — reconnecting in %ds",
                    exc,
                    _RECONNECT_DELAY,
                )
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _connect_and_listen(self) -> None:
        # asyncpg uses plain postgresql:// — strip the SQLAlchemy dialect prefix
        raw_dsn = self._dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._conn = await asyncpg.connect(raw_dsn)
        logger.info("PGListener connected, channels: %s", self._channels)

        for channel in self._channels:
            await self._conn.add_listener(channel, self._on_notify)

        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                await self._conn.execute("SELECT 1")  # keep-alive
        finally:
            await self._conn.close()

    def _on_notify(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Synchronous asyncpg callback — schedules async dispatch as a task."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "PGListener: invalid JSON on channel '%s': %s", channel, payload
            )
            return

        asyncio.get_event_loop().create_task(
            self._dispatch(channel, data),
            name=f"pg_dispatch:{channel}",
        )

    async def _dispatch(self, channel: str, data: dict) -> None:
        for handler in self._handlers:
            try:
                await handler(channel, data)
            except Exception as exc:
                logger.error(
                    "PGListener handler error on channel '%s': %s", channel, exc
                )


# Singleton — imported by main.py and handler modules
pg_listener = PGListener()
