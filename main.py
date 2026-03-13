from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import engine
from core.events_router import router as events_router
from core.grpc_client import grpc_lifespan
from core.pg_listener import pg_listener
from blueprints.router import router as blueprints_router
from jobs.router import router as jobs_router
from jobs.events import handle_db_change


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is created by scripts/setup_db.py — run it once before starting.
    pg_listener.add_channel("db_changes")
    pg_listener.add_handler(handle_db_change)
    await pg_listener.start(settings.database_url)
    async with grpc_lifespan():
        yield
    await pg_listener.stop()
    await engine.dispose()


app = FastAPI(
    title="Task Manager",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events_router, prefix="/api/v2/events", tags=["events"])
app.include_router(blueprints_router, prefix="/api/v2/blueprints", tags=["blueprints"])
app.include_router(jobs_router, prefix="/api/v2/jobs", tags=["jobs"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
