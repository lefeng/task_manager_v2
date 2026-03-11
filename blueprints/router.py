from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.grpc_client import get_stub
from blueprints import schemas, service

router = APIRouter()


# ── Runner library ────────────────────────────────────────────────────────────

@router.get("/runner/library", response_model=list[str])
async def runner_library():
    """Return the list of commands available on the connected runner."""
    from grpc_gen import job_runner_pb2
    try:
        stub = get_stub()
        response = await stub.library(job_runner_pb2.LibraryRequest())
        return list(response.library)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Runner unavailable: {exc}")


# ── Blueprints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[schemas.Blueprint])
async def list_blueprints(db: AsyncSession = Depends(get_db)):
    return await service.get_all(db)


@router.post("", response_model=schemas.Blueprint, status_code=status.HTTP_201_CREATED)
async def create_blueprint(
    data: schemas.BlueprintCreate, db: AsyncSession = Depends(get_db)
):
    return await service.create(db, data)


@router.get("/{uuid}", response_model=schemas.Blueprint)
async def get_blueprint(uuid: str, db: AsyncSession = Depends(get_db)):
    bp = await service.get(db, uuid)
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return bp


@router.patch("/{uuid}", response_model=schemas.Blueprint)
async def update_blueprint(
    uuid: str, data: schemas.BlueprintUpdate, db: AsyncSession = Depends(get_db)
):
    bp = await service.get(db, uuid)
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return await service.update(db, bp, data)


@router.delete("/{uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blueprint(uuid: str, db: AsyncSession = Depends(get_db)):
    bp = await service.get(db, uuid)
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    await service.delete(db, bp)


# ── Blueprint Arguments ───────────────────────────────────────────────────────

@router.post(
    "/{uuid}/arguments",
    response_model=schemas.BlueprintArgument,
    status_code=status.HTTP_201_CREATED,
)
async def add_argument(
    uuid: str,
    data: schemas.BlueprintArgumentCreate,
    db: AsyncSession = Depends(get_db),
):
    bp = await service.get(db, uuid)
    if not bp:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return await service.add_argument(db, bp, data)


@router.patch(
    "/{uuid}/arguments/{arg_uuid}", response_model=schemas.BlueprintArgument
)
async def update_argument(
    uuid: str,
    arg_uuid: str,
    data: schemas.BlueprintArgumentUpdate,
    db: AsyncSession = Depends(get_db),
):
    arg = await service.get_argument(db, arg_uuid)
    if not arg or arg.blueprint_uuid != uuid:
        raise HTTPException(status_code=404, detail="Argument not found")
    return await service.update_argument(db, arg, data)


@router.delete(
    "/{uuid}/arguments/{arg_uuid}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_argument(
    uuid: str, arg_uuid: str, db: AsyncSession = Depends(get_db)
):
    arg = await service.get_argument(db, arg_uuid)
    if not arg or arg.blueprint_uuid != uuid:
        raise HTTPException(status_code=404, detail="Argument not found")
    await service.delete_argument(db, arg)
