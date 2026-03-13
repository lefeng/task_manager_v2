"""
Job business logic.

All DB access is async via SQLAlchemy 2.0 + asyncpg.
State transitions are validated here — callers get an HTTPException-friendly
ValueError if a transition is illegal.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blueprints.models import Blueprint
from jobs.models import Job, JobArgument, JobState
from jobs import schemas

logger = logging.getLogger(__name__)


def cast_value(value: str, vtype: str):
    """Cast a string argument value to the type declared in the blueprint argument."""
    if value is None:
        return None
    ltype = str(vtype).lower()
    try:
        if ltype in ("int", "int32", "int64"):
            return int(float(value))
        elif ltype == "float":
            return float(value)
        elif ltype == "bool":
            if str(value).lower() in ("true", "t", "yes", "y", "on", "1"):
                return True
            elif str(value).lower() in ("false", "f", "no", "n", "off", "0"):
                return False
            raise ValueError(f"Cannot cast '{value}' to bool")
        else:
            return str(value)
    except (ValueError, TypeError):
        logger.warning("Failed to cast '%s' to %s, using raw string", value, vtype)
        return str(value)


def build_typed_arguments(job: Job) -> dict:
    """
    Return the job arguments dict with values cast to their blueprint-declared types.
    Unknown argument names fall back to raw string.
    """
    if not job.blueprint:
        return {arg.name: arg.value for arg in job.arguments}
    type_map = {bp_arg.name: bp_arg.type for bp_arg in job.blueprint.arguments}
    return {arg.name: cast_value(arg.value, type_map.get(arg.name, "string"))
            for arg in job.arguments}

# Valid state transitions: current → set of allowed next states
_TRANSITIONS: dict[int, set[int]] = {
    JobState.NOT_STARTED: {JobState.RUNNING, JobState.ABORTED},
    JobState.RUNNING:     {JobState.SUCCESS, JobState.FAILED, JobState.ABORTED},
    JobState.ABORTED:     set(),
    JobState.SUCCESS:     set(),
    JobState.FAILED:      set(),
}


def _assert_transition(current: int, next_state: int) -> None:
    allowed = _TRANSITIONS.get(current, set())
    if next_state not in allowed:
        raise ValueError(
            f"Cannot transition from {JobState(current).name} to {JobState(next_state).name}"
        )


async def get_all(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    states: list[int] | None = None,
    from_sequence_number: int | None = None,
) -> list[Job]:
    q = select(Job)
    if states:
        q = q.where(Job.state.in_(states))
    if from_sequence_number is not None:
        q = q.where(Job.sequence_number >= from_sequence_number)
    q = q.order_by(Job.sequence_number.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


async def get(db: AsyncSession, uuid: str) -> Job | None:
    return await db.get(Job, uuid)


async def create(db: AsyncSession, data: schemas.JobCreate) -> Job:
    blueprint = await db.get(Blueprint, data.blueprint_uuid)
    if not blueprint:
        raise ValueError(f"Blueprint {data.blueprint_uuid} not found")

    # Reject argument names not declared by the blueprint
    valid_names = {bp_arg.name for bp_arg in blueprint.arguments}
    for arg in data.arguments:
        if valid_names and arg.name not in valid_names:
            raise ValueError(
                f"Argument '{arg.name}' is not defined in blueprint {data.blueprint_uuid}"
            )

    job = Job(
        blueprint_uuid=data.blueprint_uuid,
        created_by=data.created_by,
        assets=data.assets,
        tags=data.tags,
        state=JobState.NOT_STARTED,
    )
    for arg in data.arguments:
        job.arguments.append(JobArgument(name=arg.name, value=arg.value))
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def delete(db: AsyncSession, job: Job) -> None:
    if job.state == JobState.RUNNING:
        raise ValueError(
            f"Cannot delete job {job.uuid} in state {JobState(job.state).name} — abort it first"
        )
    await db.delete(job)
    await db.commit()


async def mark_failed(db: AsyncSession, uuid: str) -> Job | None:
    """Force a job to FAILED — used for stale orphan detection."""
    job = await db.get(Job, uuid)
    if not job:
        return None
    job.state = JobState.FAILED
    job.date_finished = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def abort_job(db: AsyncSession, uuid: str) -> Job:
    """Transition job to ABORTED. Called after gRPC abort."""
    job = await db.get(Job, uuid)
    if not job:
        raise ValueError(f"Job {uuid} not found")
    _assert_transition(job.state, JobState.ABORTED)
    job.state = JobState.ABORTED
    job.stopped = True
    job.date_finished = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


async def apply_status_update(db: AsyncSession, job_uuid: str, update) -> Job | None:
    """
    Apply a StatusUpdate received from the gRPC stream consumer.
    `update` is a protobuf StatusUpdate message.
    """
    job = await db.get(Job, job_uuid)
    if not job:
        logger.warning("apply_status_update: job %s not found", job_uuid)
        return None

    new_state = update.state

    try:
        _assert_transition(job.state, new_state)
    except ValueError:
        # Runner may resend the current state on every tick — only log if truly unexpected
        if job.state != new_state:
            logger.debug(
                "Ignoring invalid transition %s → %s for job %s",
                JobState(job.state).name,
                new_state,
                job_uuid,
            )
        return job

    job.state = new_state
    job.progress = update.progress
    job.paused = update.paused
    if new_state == JobState.ABORTED:
        job.stopped = True

    now = datetime.now(timezone.utc)
    if new_state == JobState.RUNNING and not job.date_started:
        job.date_started = now
    if new_state in (JobState.SUCCESS, JobState.FAILED, JobState.ABORTED):
        job.date_finished = now

    await db.commit()
    await db.refresh(job)
    return job
