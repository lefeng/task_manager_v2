"""
gRPC client for the runner service.

Manages a single async channel and provides:
- Stub access for one-off calls (execute, abort, trigger, ping, library)
- Background stream consumer per job (stream_status)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import grpc

from core.config import settings

logger = logging.getLogger(__name__)

_channel: grpc.aio.Channel | None = None
_stub = None
_active_streams: dict[str, asyncio.Task] = {}


def get_stub():
    """Return the gRPC stub. Raises if channel not yet initialized."""
    if _stub is None:
        raise RuntimeError("gRPC channel not initialized — app lifespan not running")
    return _stub


@asynccontextmanager
async def grpc_lifespan():
    """Open the gRPC channel on app startup, close on shutdown."""
    global _channel, _stub
    try:
        from grpc_gen import job_runner_pb2_grpc
        _channel = grpc.aio.insecure_channel(settings.runner_grpc_addr)
        _stub = job_runner_pb2_grpc.RDSJobRunnerStub(_channel)
        logger.info("gRPC channel open → %s", settings.runner_grpc_addr)
        yield
    finally:
        # Cancel any active stream tasks
        for task in list(_active_streams.values()):
            task.cancel()
        if _active_streams:
            await asyncio.gather(*_active_streams.values(), return_exceptions=True)
        if _channel:
            await _channel.close()
        _channel = None
        _stub = None
        logger.info("gRPC channel closed")


async def start_job_stream(job_uuid: str) -> None:
    """
    Start a background asyncio task that consumes the runner's status stream
    for a job and pushes updates to the DB and WebSocket clients.

    Safe to call multiple times — existing stream for the same uuid is cancelled first.
    """
    # Cancel stale stream if any
    await cancel_job_stream(job_uuid)

    task = asyncio.create_task(
        _consume_stream(job_uuid),
        name=f"stream:{job_uuid}",
    )
    _active_streams[job_uuid] = task
    task.add_done_callback(lambda _: _active_streams.pop(job_uuid, None))


async def cancel_job_stream(job_uuid: str) -> None:
    if task := _active_streams.get(job_uuid):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _consume_stream(job_uuid: str) -> None:
    """
    Core stream consumer loop.
    Receives StatusUpdate messages from runner and:
      1. Writes state/progress to the DB
      2. Broadcasts to any connected WebSocket clients
    """
    from grpc_gen import job_runner_pb2
    from core.database import AsyncSessionLocal
    from jobs import service as job_service
    from jobs.ws_manager import manager

    stub = get_stub()
    request = job_runner_pb2.StatusStreamRequest(job_uuid=job_uuid)

    try:
        async for update in stub.StreamStatus(request):
            # Persist to DB
            async with AsyncSessionLocal() as db:
                await job_service.apply_status_update(db, job_uuid, update)

            # Push to WebSocket clients
            await manager.broadcast(job_uuid, {
                "uuid": job_uuid,
                "state": update.state,
                "progress": update.progress,
                "paused": update.paused,
                "task_statuses": list(update.task_statuses),
            })

    except grpc.aio.AioRpcError as exc:
        logger.warning("Stream ended for job %s: %s", job_uuid, exc.code())
        # Runner went away — mark job FAILED if it is still in an active state
        async with AsyncSessionLocal() as db:
            job = await job_service.get(db, job_uuid)
            if job and job.state not in (
                job_service.JobState.SUCCESS,
                job_service.JobState.FAILED,
                job_service.JobState.ABORTED,
            ):
                logger.warning("Marking job %s FAILED due to lost runner stream", job_uuid)
                await job_service.mark_failed(db, job_uuid)
    except asyncio.CancelledError:
        logger.debug("Stream cancelled for job %s", job_uuid)
        raise
    except Exception:
        logger.exception("Unexpected error in stream consumer for job %s", job_uuid)
        async with AsyncSessionLocal() as db:
            job = await job_service.get(db, job_uuid)
            if job and job.state not in (
                job_service.JobState.SUCCESS,
                job_service.JobState.FAILED,
                job_service.JobState.ABORTED,
            ):
                await job_service.mark_failed(db, job_uuid)
