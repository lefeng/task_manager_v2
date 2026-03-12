"""
Handler for PostgreSQL LISTEN/NOTIFY events on the 'jobs' table.

Flow:
    PGListener receives notification on 'jobs_changes'
        → handle_jobs_change() is called
            → for insert/update: fetch uuid, sequence_number, state from DB
            → for delete: use uuid from notification payload (row is gone)
        → broadcast to all EventWSManager clients

Message format sent to WebSocket clients:
    {
        "topic": "jobs",
        "event": "insert" | "update" | "delete",
        "data": {
            "uuid": "...",
            "sequence_number": 42,   # absent on delete
            "state": 2               # absent on delete
        }
    }
"""

import logging

from sqlalchemy import select

from core.database import AsyncSessionLocal
from jobs.models import Job
from jobs.ws_manager import event_manager

logger = logging.getLogger(__name__)


async def handle_jobs_change(channel: str, data: dict) -> None:
    event = data.get("event")
    uuid = data.get("uuid")

    if not uuid:
        logger.warning("jobs_changes notification missing uuid: %s", data)
        return

    if event == "delete":
        payload = {"topic": "jobs", "event": "delete", "data": {"uuid": uuid}}
        await event_manager.broadcast(payload)
        return

    if event in ("insert", "update"):
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(Job.uuid, Job.sequence_number, Job.state).where(Job.uuid == uuid)
            )
            job = row.first()

        if job is None:
            logger.debug(
                "jobs_changes: job %s not found after %s (already deleted?)",
                uuid,
                event,
            )
            return

        payload = {
            "topic": "jobs",
            "event": event,
            "data": {
                "uuid": job.uuid,
                "sequence_number": job.sequence_number,
                "state": job.state,
            },
        }
        await event_manager.broadcast(payload)
        return

    logger.warning("jobs_changes: unknown event type '%s'", event)
