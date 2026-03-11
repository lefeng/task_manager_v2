import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Blueprint(Base):
    __tablename__ = "blueprints"

    uuid: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    executor: Mapped[str] = mapped_column(String(255))
    command: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full task definition JSON — passed verbatim to runner
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    # Simple string tags stored as JSONB array
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    arguments: Mapped[list["BlueprintArgument"]] = relationship(
        back_populates="blueprint",
        cascade="all, delete-orphan",
        order_by="BlueprintArgument.order",
        lazy="selectin",
    )


class BlueprintArgument(Base):
    __tablename__ = "blueprint_arguments"

    uuid: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    blueprint_uuid: Mapped[str] = mapped_column(
        ForeignKey("blueprints.uuid", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(64), default="string")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # UI hints for the frontend (widget type, min/max, options, etc.)
    ui: Mapped[dict] = mapped_column(JSON, default=dict)
    order: Mapped[int] = mapped_column(Integer, default=0)

    blueprint: Mapped["Blueprint"] = relationship(back_populates="arguments")
