from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BlueprintArgumentBase(BaseModel):
    name: str
    type: str = "string"
    description: str | None = None
    ui: dict = {}
    order: int = 0


class BlueprintArgumentCreate(BlueprintArgumentBase):
    pass


class BlueprintArgumentUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    ui: dict | None = None
    order: int | None = None


class BlueprintArgument(BlueprintArgumentBase):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    blueprint_uuid: str


class BlueprintBase(BaseModel):
    executor: str
    command: str
    description: str | None = None
    definition: dict = {}
    tags: list[str] = []


class BlueprintCreate(BlueprintBase):
    arguments: list[BlueprintArgumentCreate] = []


class BlueprintUpdate(BaseModel):
    executor: str | None = None
    command: str | None = None
    description: str | None = None
    definition: dict | None = None
    tags: list[str] | None = None


class Blueprint(BlueprintBase):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    created_at: datetime
    updated_at: datetime
    arguments: list[BlueprintArgument] = []
