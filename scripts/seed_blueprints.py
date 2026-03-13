"""
Seed blueprints from the old task_manager SQLite database into the new
PostgreSQL taskman database.

Usage (from project root):
    python scripts/seed_blueprints.py --sqlite /path/to/old/taskman.db

Or to seed from a JSON file (exported manually):
    python scripts/seed_blueprints.py --json /path/to/blueprints.json

The JSON format expected:
[
  {
    "uuid": "...",
    "executor": "actin",
    "command": "trip_single",
    "description": "...",
    "definition": {},
    "tags": [],
    "arguments": [
      {"name": "speed", "type": "float", "description": "...", "ui": {}, "order": 0}
    ]
  }
]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from core.config import settings
from core.database import Base
from blueprints.models import Blueprint, BlueprintArgument
import blueprints.models  # noqa: F401 — register models
import jobs.models  # noqa: F401 — register models


async def seed_from_records(session: AsyncSession, records: list[dict]) -> None:
    inserted = 0
    skipped = 0

    for rec in records:
        existing = await session.get(Blueprint, rec["uuid"])
        if existing:
            print(f"  skip (already exists): {rec['uuid']} — {rec.get('command')}")
            skipped += 1
            continue

        bp = Blueprint(
            uuid=rec["uuid"],
            executor=rec.get("executor", ""),
            command=rec.get("command", ""),
            description=rec.get("description"),
            definition=rec.get("definition") or {},
            tags=rec.get("tags") or [],
        )
        for i, arg in enumerate(rec.get("arguments") or []):
            bp.arguments.append(
                BlueprintArgument(
                    uuid=arg.get("uuid") or None,
                    name=arg["name"],
                    type=arg.get("type", "string"),
                    description=arg.get("description"),
                    ui=arg.get("ui") or {},
                    order=arg.get("order", i),
                )
            )
        session.add(bp)
        inserted += 1
        print(f"  insert: {rec['uuid']} — {rec.get('executor')}:{rec.get('command')}")

    await session.commit()
    print(f"\nDone. Inserted: {inserted}  Skipped: {skipped}")


async def seed_from_json(json_path: str) -> None:
    data = json.loads(Path(json_path).read_text())
    if isinstance(data, dict):
        data = data.get("blueprints", list(data.values()))

    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await seed_from_records(session, data)
    await engine.dispose()


async def seed_from_sqlite(sqlite_path: str) -> None:
    import sqlite3

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row

    # Read blueprints
    blueprints_raw = conn.execute(
        "SELECT uuid, executor, command, description, definition FROM blueprint_job"
    ).fetchall()

    # Read arguments
    args_raw = conn.execute(
        "SELECT uuid, blueprint_uuid, name, type, description, ui FROM blueprint_argument"
    ).fetchall()
    conn.close()

    # Group arguments by blueprint
    args_by_bp: dict[str, list] = {}
    for arg in args_raw:
        args_by_bp.setdefault(arg["blueprint_uuid"], []).append(
            {
                "uuid": arg["uuid"],
                "name": arg["name"],
                "type": arg["type"] or "string",
                "description": arg["description"],
                "ui": json.loads(arg["ui"]) if arg["ui"] else {},
            }
        )

    records = []
    for bp in blueprints_raw:
        definition = bp["definition"]
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except (json.JSONDecodeError, TypeError):
                definition = {}

        records.append(
            {
                "uuid": bp["uuid"],
                "executor": bp["executor"] or "",
                "command": bp["command"] or "",
                "description": bp["description"],
                "definition": definition or {},
                "tags": [],
                "arguments": args_by_bp.get(bp["uuid"], []),
            }
        )

    print(f"Found {len(records)} blueprints in SQLite.")
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        await seed_from_records(session, records)
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed taskman blueprints")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--sqlite", metavar="PATH", help="Path to old task_manager SQLite DB"
    )
    group.add_argument("--json", metavar="PATH", help="Path to blueprints JSON export")
    args = parser.parse_args()

    if args.sqlite:
        asyncio.run(seed_from_sqlite(args.sqlite))
    else:
        asyncio.run(seed_from_json(args.json))


if __name__ == "__main__":
    main()
