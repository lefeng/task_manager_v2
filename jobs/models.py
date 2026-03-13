import uuid
from datetime import datetime, timezone
from enum import IntEnum

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Float,
    Boolean,
    Sequence,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

# PostgreSQL sequence for display-friendly sequential job numbers
job_seq = Sequence("job_seq", metadata=Base.metadata)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobState(IntEnum):
    NOT_STARTED = 0
    RUNNING = 2
    ABORTED = 4
    SUCCESS = 5
    FAILED = 6


class Job(Base):
    __tablename__ = "jobs"

    uuid: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Human-readable sequential number (e.g. #42)
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        job_seq,
        server_default=job_seq.next_value(),
        unique=True,
        index=True,
    )
    blueprint_uuid: Mapped[str] = mapped_column(
        ForeignKey("blueprints.uuid", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[int] = mapped_column(Integer, default=JobState.NOT_STARTED)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Arbitrary asset references (e.g. tubular UUIDs, location refs)
    assets: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    date_created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    date_modified: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    date_started: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    date_finished: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    arguments: Mapped[list["JobArgument"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    blueprint: Mapped["blueprints.models.Blueprint | None"] = relationship(  # type: ignore[name-defined]
        "Blueprint",
        lazy="selectin",
    )


class JobArgument(Base):
    __tablename__ = "job_arguments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(ForeignKey("jobs.uuid", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text, default="")

    job: Mapped["Job"] = relationship(back_populates="arguments")
