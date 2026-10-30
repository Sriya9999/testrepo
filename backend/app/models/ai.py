import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class AiRun(IdMixin, TimestampMixin, TenantMixin, Base):
    """One orchestrated agent workflow started from an instruction."""

    __tablename__ = "ai_runs"

    instruction: Mapped[str] = mapped_column(Text)
    # queued | running | awaiting_approval | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    plan: Mapped[dict] = mapped_column(default=dict)
    output: Mapped[dict] = mapped_column(default=dict)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiTask(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "ai_tasks"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | done | failed | skipped
    output: Mapped[dict] = mapped_column(default=dict)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiExecutionLog(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "ai_execution_logs"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_tasks.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(default=dict)


class Approval(IdMixin, TimestampMixin, TenantMixin, Base):
    """A proposed action that must be approved before it executes."""

    __tablename__ = "approvals"

    # publish_post | schedule_post | approve_content | launch_campaign | increase_budget |
    # modify_campaign | pause_campaign
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(300))
    platform: Mapped[str | None] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(default=dict)  # exactly what will execute
    payload_hash: Mapped[str] = mapped_column(String(64))
    budget_impact_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    ai_reasoning: Mapped[str | None] = mapped_column(Text)
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    # pending | approved | rejected | changes_requested | executed | failed | superseded
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(index=True)  # e.g. the agent run that proposed it
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_by_agent: Mapped[str | None] = mapped_column(String(40))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    execution_result: Mapped[dict] = mapped_column(default=dict)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
