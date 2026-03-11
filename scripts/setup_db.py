"""
Create the taskman database (if needed) and all tables.

Run once before starting the app:
    python scripts/setup_db.py

To recreate tables from scratch (DESTROYS ALL DATA):
    python scripts/setup_db.py --drop
"""

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings
from core.database import engine, Base
import blueprints.models  # noqa: F401
import jobs.models  # noqa: F401


def _maintenance_url(database_url: str) -> str:
    """Swap the target database to 'postgres' for the CREATE DATABASE command."""
    # e.g. postgresql+asyncpg://ipc:dreamteam@localhost:5432/taskman
    #   -> postgresql+asyncpg://ipc:dreamteam@localhost:5432/postgres
    parts = database_url.rsplit("/", 1)
    return f"{parts[0]}/postgres"


async def create_database() -> None:
    """Connect to the 'postgres' maintenance DB and create taskman if missing."""
    db_name = settings.database_url.rsplit("/", 1)[-1]
    # asyncpg needs the raw URL without the +asyncpg dialect prefix
    raw_url = _maintenance_url(settings.database_url).replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(raw_url)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if exists:
            print(f"Database '{db_name}' already exists.")
        else:
            # CREATE DATABASE cannot run inside a transaction
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Database '{db_name}' created.")
    finally:
        await conn.close()


async def setup(drop: bool = False) -> None:
    await create_database()

    async with engine.begin() as conn:
        if drop:
            print("Dropping all tables...")
            await conn.run_sync(Base.metadata.drop_all)
        print("Creating tables...")
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="Drop all tables first (DESTROYS DATA)")
    args = parser.parse_args()
    asyncio.run(setup(drop=args.drop))
