"""
Handler for PostgreSQL LISTEN/NOTIFY events on the 'db_changes' channel.

Flow:
    PGListener receives notification on 'db_changes'
        → handle_db_change() dispatches by topic
            → _handle_jobs_change()      for topic='jobs'
            → _handle_blueprints_change() for topic='blueprints'
        → broadcast to all EventWSManager clients

Child-table changes (job_arguments, blueprint_arguments) bubble up to their
parent topic as 'update' events — see setup_db.py trigger definitions.

Message format sent to WebSocket clients:
    {
        "topic": "jobs" | "blueprints",
        "event": "insert" | "update" | "delete",
        "data": {
            # jobs insert/update:
            "uuid": "...", "sequence_number": 42, "state": 2, "progress": 0.45
            # blueprints insert/update:
            "uuid": "...", "executor": "...", "command": "...", "description": "..."
            # delete (either topic):
            "uuid": "..."
        }
    }
"""

import logging

from sqlalchemy import select

from blueprints.models import Blueprint
from core.database import AsyncSessionLocal
from core.event_manager import event_manager
from jobs.models import Job

logger = logging.getLogger(__name__)


async def handle_db_change(channel: str, data: dict) -> None:
    topic = data.get("topic")
    if topic == "jobs":
        await _handle_jobs_change(data)
    elif topic == "blueprints":
        await _handle_blueprints_change(data)
    else:
        logger.warning("db_changes: unknown topic '%s' — data: %s", topic, data)


async def _handle_jobs_change(data: dict) -> None:
    event = data.get("event")
    uuid = data.get("uuid")

    if not uuid:
        logger.warning("db_changes/jobs: missing uuid — data: %s", data)
        return

    if event == "delete":
        await event_manager.broadcast(
            {"topic": "jobs", "event": "delete", "data": {"uuid": uuid}}
        )
        return

    if event in ("insert", "update"):
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(Job.uuid, Job.sequence_number, Job.state, Job.progress).where(
                    Job.uuid == uuid
                )
            )
            job = row.first()

        if job is None:
            logger.debug(
                "db_changes/jobs: job %s not found after %s (already deleted?)",
                uuid,
                event,
            )
            return

        await event_manager.broadcast(
            {
                "topic": "jobs",
                "event": event,
                "data": {
                    "uuid": job.uuid,
                    "sequence_number": job.sequence_number,
                    "state": job.state,
                    "progress": job.progress,
                },
            }
        )
        return

    logger.warning("db_changes/jobs: unknown event type '%s'", event)


async def _handle_blueprints_change(data: dict) -> None:
    event = data.get("event")
    uuid = data.get("uuid")

    if not uuid:
        logger.warning("db_changes/blueprints: missing uuid — data: %s", data)
        return

    if event == "delete":
        await event_manager.broadcast(
            {"topic": "blueprints", "event": "delete", "data": {"uuid": uuid}}
        )
        return

    if event in ("insert", "update"):
        async with AsyncSessionLocal() as session:
            row = await session.execute(
                select(
                    Blueprint.uuid,
                    Blueprint.executor,
                    Blueprint.command,
                    Blueprint.description,
                ).where(Blueprint.uuid == uuid)
            )
            bp = row.first()

        if bp is None:
            logger.debug(
                "db_changes/blueprints: blueprint %s not found after %s (already deleted?)",
                uuid,
                event,
            )
            return

        await event_manager.broadcast(
            {
                "topic": "blueprints",
                "event": event,
                "data": {
                    "uuid": bp.uuid,
                    "executor": bp.executor,
                    "command": bp.command,
                    "description": bp.description,
                },
            }
        )
        return

    logger.warning("db_changes/blueprints: unknown event type '%s'", event)
