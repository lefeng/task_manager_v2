"""
Jobs router.

REST endpoints:
  GET    /api/v2/jobs                  — list jobs
  POST   /api/v2/jobs                  — create job from blueprint
  GET    /api/v2/jobs/{uuid}           — get job
  DELETE /api/v2/jobs/{uuid}           — delete job
  POST   /api/v2/jobs/{uuid}/run       — execute job on runner
  POST   /api/v2/jobs/{uuid}/abort     — abort running job
  POST   /api/v2/jobs/{uuid}/trigger   — send event to running job (pause/resume/custom)

WebSocket:
  WS  /api/v2/jobs/ws                 — gRPC stream: live status updates for ALL running jobs
  WS  /api/v2/jobs/{uuid}/ws          — gRPC stream: live status updates for a single job
"""

import json
import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
    Query,
)
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.grpc_client import get_stub, start_job_stream, cancel_job_stream
from jobs import schemas, service
from jobs.job_status_manager import job_status_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── REST ──────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[schemas.Job])
async def list_jobs(
    limit: Annotated[int, Query(le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    state: Annotated[
        list[int] | None, Query(description="Filter by one or more JobState values")
    ] = None,
    from_sequence_number: Annotated[int | None, Query(ge=0)] = None,
    db: AsyncSession = Depends(get_db),
):
    return await service.get_all(
        db,
        limit=limit,
        offset=offset,
        states=state,
        from_sequence_number=from_sequence_number,
    )


@router.post("", response_model=schemas.Job, status_code=status.HTTP_201_CREATED)
async def create_job(data: schemas.JobCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await service.create(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{uuid}", response_model=schemas.Job)
async def get_job(uuid: str, db: AsyncSession = Depends(get_db)):
    job = await service.get(db, uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/{uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(uuid: str, db: AsyncSession = Depends(get_db)):
    job = await service.get(db, uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        await service.delete(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{uuid}/run", response_model=schemas.Job)
async def run_job(uuid: str, db: AsyncSession = Depends(get_db)):
    """
    Call gRPC execute on the runner, then open a background stream to receive status updates.

    If the job is already RUNNING, checks whether it is actually present on
    the runner — if not, marks it FAILED (stale orphan detection).
    """
    from grpc_gen import job_runner_pb2

    job = await service.get(db, uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.blueprint:
        raise HTTPException(status_code=400, detail="Job has no associated blueprint")

    # Stale orphan detection: job thinks it's RUNNING but runner has no record of it
    if job.state == service.JobState.RUNNING:
        try:
            stub = get_stub()
            running = await stub.jobs(job_runner_pb2.JobsRequest())
            if uuid not in running.job_uuids:
                await service.mark_failed(db, uuid)
                raise HTTPException(
                    status_code=409,
                    detail=f"Job {uuid} is marked RUNNING but is not present on the runner — marked FAILED",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Could not check runner jobs for stale detection: %s", exc)

    # Cast argument values to their blueprint-declared types before sending
    typed_args = service.build_typed_arguments(job)

    try:
        stub = get_stub()
        response = await stub.execute(
            job_runner_pb2.ExecuteRequest(
                uuid=uuid,
                command=f"{job.blueprint.executor}:{job.blueprint.command}",
                arguments=json.dumps(typed_args),
                job_url="",  # runner pushes via gRPC stream, not REST
            )
        )
    except Exception as exc:
        logger.error("gRPC execute failed for job %s: %s", uuid, exc)
        raise HTTPException(status_code=502, detail=f"Runner unavailable: {exc}")

    if not response.success:
        raise HTTPException(status_code=400, detail="Runner rejected the job")

    # Start background asyncio task: runner → DB + WebSocket
    await start_job_stream(uuid)

    return job


@router.post("/{uuid}/abort", response_model=schemas.Job)
async def abort_job(uuid: str, db: AsyncSession = Depends(get_db)):
    """
    Abort a job.
    - NOT_STARTED: DB-only, no gRPC call needed (job never reached the runner).
    - RUNNING: call gRPC abort then update DB.
    """
    from grpc_gen import job_runner_pb2

    job = await service.get(db, uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.state == service.JobState.NOT_STARTED:
        # Never sent to runner — just cancel locally
        return await service.abort_job(db, uuid)

    try:
        stub = get_stub()
        await stub.abort(job_runner_pb2.AbortRequest(uuid=uuid))
    except Exception as exc:
        logger.error("gRPC abort failed for job %s: %s", uuid, exc)
        raise HTTPException(status_code=502, detail=f"Runner unavailable: {exc}")

    await cancel_job_stream(uuid)
    return await service.abort_job(db, uuid)


@router.post("/{uuid}/trigger", response_model=schemas.Job)
async def trigger_job(
    uuid: str, data: schemas.TriggerRequest, db: AsyncSession = Depends(get_db)
):
    from grpc_gen import job_runner_pb2

    job = await service.get(db, uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        stub = get_stub()
        response = await stub.trigger(
            job_runner_pb2.TriggerRequest(
                job_uuid=uuid,
                event=data.event,
                arguments=json.dumps(data.arguments),
            )
        )
    except Exception as exc:
        logger.error("gRPC trigger failed for job %s: %s", uuid, exc)
        raise HTTPException(status_code=502, detail=f"Runner unavailable: {exc}")

    if not response.success:
        raise HTTPException(status_code=400, detail="Runner rejected the trigger")

    return job


# ── WebSocket ─────────────────────────────────────────────────────────────────


@router.websocket("/ws")
async def jobs_ws_global(ws: WebSocket, db: AsyncSession = Depends(get_db)):
    """
    Global real-time stream — receives every job update across all running jobs.

    On connect: sends the current state of every non-terminal job.
    Then: receives push updates whenever any job changes state.
    """
    await job_status_manager.connect_global(ws)

    # Snapshot all active (non-terminal) jobs immediately on connect
    active = await service.get_all(
        db,
        limit=500,
        states=[service.JobState.RUNNING],
    )
    for job in active:
        await ws.send_json(schemas.Job.model_validate(job).model_dump(mode="json"))

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        job_status_manager.disconnect_global(ws)


@router.websocket("/{uuid}/ws")
async def job_ws(uuid: str, ws: WebSocket, db: AsyncSession = Depends(get_db)):
    """
    Real-time job status stream.

    On connect: sends current job state immediately so the client is in sync.
    Then: receives push updates from the gRPC stream consumer until disconnect.
    """
    job = await service.get(db, uuid)
    if not job:
        await ws.close(code=4004, reason="Job not found")
        return

    await job_status_manager.connect(uuid, ws)

    # Send current state immediately on connect
    await ws.send_json(schemas.Job.model_validate(job).model_dump(mode="json"))

    try:
        while True:
            # Keep connection alive; client can send pings as text
            await ws.receive_text()
    except WebSocketDisconnect:
        job_status_manager.disconnect(uuid, ws)
