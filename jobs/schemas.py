from datetime import datetime

from pydantic import BaseModel, ConfigDict

from jobs.models import JobState


class JobArgumentBase(BaseModel):
    name: str
    value: str = ""


class JobArgumentCreate(JobArgumentBase):
    pass


class JobArgument(JobArgumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_uuid: str


class JobCreate(BaseModel):
    blueprint_uuid: str
    created_by: str | None = None
    assets: dict = {}
    tags: list[str] = []
    arguments: list[JobArgumentCreate] = []


class JobUpdate(BaseModel):
    """Used internally by the gRPC stream consumer — not exposed on the API."""
    state: int | None = None
    progress: float | None = None
    paused: bool | None = None
    stopped: bool | None = None
    date_started: datetime | None = None
    date_finished: datetime | None = None


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    sequence_number: int
    blueprint_uuid: str | None
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


class JobStateLabel(BaseModel):
    """Convenience: state int + human label."""
    value: int
    label: str

    @classmethod
    def from_state(cls, state: int) -> "JobStateLabel":
        return cls(value=state, label=JobState(state).name)


class TriggerRequest(BaseModel):
    event: str
    arguments: dict = {}
