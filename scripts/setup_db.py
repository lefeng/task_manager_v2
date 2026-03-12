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

from sqlalchemy import text

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


async def setup_triggers() -> None:
    """Create (or replace) the PostgreSQL trigger that notifies on jobs changes."""
    async with engine.begin() as conn:
        # Trigger function: sends only the uuid and operation type.
        # Payload is intentionally minimal to stay well under the 8KB NOTIFY limit.
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION notify_jobs_change()
            RETURNS trigger AS $$
            DECLARE
                row_uuid TEXT;
            BEGIN
                row_uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.uuid ELSE NEW.uuid END;
                PERFORM pg_notify(
                    'jobs_changes',
                    json_build_object('event', lower(TG_OP), 'uuid', row_uuid)::text
                );
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """))

        await conn.execute(text("DROP TRIGGER IF EXISTS jobs_notify ON jobs;"))

        await conn.execute(text("""
            CREATE TRIGGER jobs_notify
            AFTER INSERT OR UPDATE OF uuid, sequence_number, state OR DELETE ON jobs
            FOR EACH ROW EXECUTE FUNCTION notify_jobs_change();
        """))

    print("Triggers created.")


async def setup(drop: bool = False) -> None:
    await create_database()

    async with engine.begin() as conn:
        if drop:
            print("Dropping all tables...")
            await conn.run_sync(Base.metadata.drop_all)
        print("Creating tables...")
        await conn.run_sync(Base.metadata.create_all)

    await setup_triggers()

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="Drop all tables first (DESTROYS DATA)")
    args = parser.parse_args()
    asyncio.run(setup(drop=args.drop))
