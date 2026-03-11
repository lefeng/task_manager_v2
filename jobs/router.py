"""
Jobs router.

REST endpoints:
  GET    /api/v2/jobs              — list jobs
  POST   /api/v2/jobs              — create job from blueprint
  GET    /api/v2/jobs/{uuid}       — get job
  DELETE /api/v2/jobs/{uuid}       — delete job
  POST   /api/v2/jobs/{uuid}/run   — queue + execute job on runner
  POST   /api/v2/jobs/{uuid}/abort — abort running job
  POST   /api/v2/jobs/{uuid}/trigger — send event to running job (pause/resume/custom)

WebSocket:
  WS     /api/v2/jobs/{uuid}/ws   — real-time status stream for a job
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.grpc_client import get_stub, start_job_stream, cancel_job_stream
from jobs import schemas, service
from jobs.ws_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── REST ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[schemas.Job])
async def list_jobs(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    state: list[int] | None = Query(None, description="Filter by one or more JobState values"),
    from_sequence_number: int | None = Query(None, ge=0),
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
    return await service.create(db, data)


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
    Queue the job in the DB, call gRPC execute on the runner,
    then open a background stream to receive status updates.
    """
    from grpc_gen import job_runner_pb2

    job = await service.queue_job(db, uuid)

    if not job.blueprint:
        raise HTTPException(status_code=400, detail="Job has no associated blueprint")

    arguments_json = json.dumps(
        {arg.name: arg.value for arg in job.arguments}
    )

    try:
        stub = get_stub()
        response = await stub.execute(
            job_runner_pb2.ExecuteRequest(
                uuid=uuid,
                command=f"{job.blueprint.executor}:{job.blueprint.command}",
                arguments=arguments_json,
                # job_url left empty — runner pushes via gRPC stream, not REST
                job_url="",
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
    from grpc_gen import job_runner_pb2

    job = await service.get(db, uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

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

    await manager.connect(uuid, ws)

    # Send current state immediately on connect
    await ws.send_json(schemas.Job.model_validate(job).model_dump(mode="json"))

    try:
        while True:
            # Keep connection alive; client can send pings as text
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(uuid, ws)
