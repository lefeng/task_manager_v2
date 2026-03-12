from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobArgumentBase(BaseModel):
    name: str
    value: str = ""


class JobArgumentCreate(JobArgumentBase):
    pass


class JobArgument(JobArgumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_uuid: str


class JobBlueprint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    description: str | None


class JobCreate(BaseModel):
    blueprint_uuid: str
    created_by: str | None = None
    assets: dict = {}
    tags: list[str] = []
    arguments: list[JobArgumentCreate] = []


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    sequence_number: int
    blueprint: JobBlueprint | None = None
    state: int
    progress: float
    paused: bool
    stopped: bool
    created_by: str | None
    assets: dict
    tags: list
    date_created: datetime
    date_modified: datetime
    date_started: datetime | None
    date_finished: datetime | None
    arguments: list[JobArgument] = []


class TriggerRequest(BaseModel):
    event: str
    arguments: dict = {}
