from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blueprints.models import Blueprint, BlueprintArgument
from blueprints import schemas


async def get_all(db: AsyncSession) -> list[Blueprint]:
    result = await db.execute(select(Blueprint).order_by(Blueprint.created_at.desc()))
    return result.scalars().all()


async def get(db: AsyncSession, uuid: str) -> Blueprint | None:
    return await db.get(Blueprint, uuid)


async def create(db: AsyncSession, data: schemas.BlueprintCreate) -> Blueprint:
    blueprint = Blueprint(
        executor=data.executor,
        command=data.command,
        description=data.description,
        definition=data.definition,
        tags=data.tags,
    )
    for arg_data in data.arguments:
        blueprint.arguments.append(
            BlueprintArgument(**arg_data.model_dump())
        )
    db.add(blueprint)
    await db.commit()
    await db.refresh(blueprint)
    return blueprint


async def update(
    db: AsyncSession, blueprint: Blueprint, data: schemas.BlueprintUpdate
) -> Blueprint:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(blueprint, field, value)
    await db.commit()
    await db.refresh(blueprint)
    return blueprint


async def delete(db: AsyncSession, blueprint: Blueprint) -> None:
    await db.delete(blueprint)
    await db.commit()


async def add_argument(
    db: AsyncSession, blueprint: Blueprint, data: schemas.BlueprintArgumentCreate
) -> BlueprintArgument:
    arg = BlueprintArgument(blueprint_uuid=blueprint.uuid, **data.model_dump())
    db.add(arg)
    await db.commit()
    await db.refresh(arg)
    return arg


async def update_argument(
    db: AsyncSession, arg: BlueprintArgument, data: schemas.BlueprintArgumentUpdate
) -> BlueprintArgument:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(arg, field, value)
    await db.commit()
    await db.refresh(arg)
    return arg


async def delete_argument(db: AsyncSession, arg: BlueprintArgument) -> None:
    await db.delete(arg)
    await db.commit()


async def get_argument(db: AsyncSession, uuid: str) -> BlueprintArgument | None:
    return await db.get(BlueprintArgument, uuid)
