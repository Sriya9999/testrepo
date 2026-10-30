import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TimestampMixin, utcnow


class Job(IdMixin, TimestampMixin, Base):
    """Background work: generation, crawling, publishing, syncing, GEO monitoring."""

    __tablename__ = "jobs"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(default=dict)
    # queued | running | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_type: Mapped[str] = mapped_column(String(10))  # user | agent | system
    actor_id: Mapped[uuid.UUID | None]
    actor_label: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushDevice(IdMixin, TimestampMixin, Base):
    __tablename__ = "push_devices"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(300), unique=True)
    platform: Mapped[str] = mapped_column(String(10))  # ios | android
