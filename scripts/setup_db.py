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
from sqlalchemy.engine import make_url

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
    raw_url = (
        make_url(_maintenance_url(settings.database_url))
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )

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
    """Create (or replace) all PostgreSQL NOTIFY triggers for the db_changes channel.

    All four tables notify the single 'db_changes' channel.  Payloads are
    intentionally minimal (topic + event + uuid) to stay well under the 8 KB
    NOTIFY limit.  Child-table changes bubble up to the parent topic so clients
    only need to handle 'jobs' and 'blueprints' topics.
    """
    async with engine.begin() as conn:
        # ── trigger functions ──────────────────────────────────────────────────

        # Generic function for top-level tables.  TG_ARGV[0] = topic name.
        await conn.execute(
            text(
                """
            CREATE OR REPLACE FUNCTION notify_table_change()
            RETURNS trigger AS $$
            DECLARE
                row_uuid TEXT;
            BEGIN
                row_uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.uuid ELSE NEW.uuid END;
                PERFORM pg_notify(
                    'db_changes',
                    json_build_object('topic', TG_ARGV[0], 'event', lower(TG_OP), 'uuid', row_uuid)::text
                );
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """
            )
        )

        # job_arguments → bubbles up to the jobs topic as an 'update'.
        await conn.execute(
            text(
                """
            CREATE OR REPLACE FUNCTION notify_job_argument_change()
            RETURNS trigger AS $$
            DECLARE
                parent_uuid TEXT;
            BEGIN
                parent_uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_uuid ELSE NEW.job_uuid END;
                PERFORM pg_notify(
                    'db_changes',
                    json_build_object('topic', 'jobs', 'event', 'update', 'uuid', parent_uuid)::text
                );
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """
            )
        )

        # blueprint_arguments → bubbles up to the blueprints topic as an 'update'.
        await conn.execute(
            text(
                """
            CREATE OR REPLACE FUNCTION notify_blueprint_argument_change()
            RETURNS trigger AS $$
            DECLARE
                parent_uuid TEXT;
            BEGIN
                parent_uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.blueprint_uuid ELSE NEW.blueprint_uuid END;
                PERFORM pg_notify(
                    'db_changes',
                    json_build_object('topic', 'blueprints', 'event', 'update', 'uuid', parent_uuid)::text
                );
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """
            )
        )

        # ── drop old triggers ──────────────────────────────────────────────────
        await conn.execute(text("DROP TRIGGER IF EXISTS jobs_notify ON jobs;"))
        await conn.execute(
            text("DROP TRIGGER IF EXISTS blueprints_notify ON blueprints;")
        )
        await conn.execute(
            text("DROP TRIGGER IF EXISTS job_arguments_notify ON job_arguments;")
        )
        await conn.execute(
            text(
                "DROP TRIGGER IF EXISTS blueprint_arguments_notify ON blueprint_arguments;"
            )
        )

        # ── create triggers ────────────────────────────────────────────────────

        # jobs: selective columns only — paused/stopped are not watched because
        # they're managed internally alongside state; progress is watched so
        # clients receive updates via the events channel.
        await conn.execute(
            text(
                """
            CREATE TRIGGER jobs_notify
            AFTER INSERT OR UPDATE OF uuid, sequence_number, state, progress OR DELETE ON jobs
            FOR EACH ROW EXECUTE FUNCTION notify_table_change('jobs');
        """
            )
        )

        # blueprints: fire on any change (creates, edits, deletes are all rare).
        await conn.execute(
            text(
                """
            CREATE TRIGGER blueprints_notify
            AFTER INSERT OR UPDATE OR DELETE ON blueprints
            FOR EACH ROW EXECUTE FUNCTION notify_table_change('blueprints');
        """
            )
        )

        # job_arguments: UPDATE/DELETE only — INSERT is skipped because arguments are
        # written at job creation time; the parent jobs INSERT event already covers that.
        await conn.execute(
            text(
                """
            CREATE TRIGGER job_arguments_notify
            AFTER UPDATE OR DELETE ON job_arguments
            FOR EACH ROW EXECUTE FUNCTION notify_job_argument_change();
        """
            )
        )

        # blueprint_arguments: UPDATE/DELETE only — same reasoning as job_arguments.
        await conn.execute(
            text(
                """
            CREATE TRIGGER blueprint_arguments_notify
            AFTER UPDATE OR DELETE ON blueprint_arguments
            FOR EACH ROW EXECUTE FUNCTION notify_blueprint_argument_change();
        """
            )
        )

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
    parser.add_argument(
        "--drop", action="store_true", help="Drop all tables first (DESTROYS DATA)"
    )
    args = parser.parse_args()
    asyncio.run(setup(drop=args.drop))
