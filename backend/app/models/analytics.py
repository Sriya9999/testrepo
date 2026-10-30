import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class PerformanceSnapshot(IdMixin, TimestampMixin, TenantMixin, Base):
    """Daily channel-level metrics synced from GA4, Search Console and social platforms.
    Ad spend lives in AdInsight; GEO visibility is computed from GeoResult."""

    __tablename__ = "performance_snapshots"
    __table_args__ = (UniqueConstraint("workspace_id", "channel", "date", "source"),)

    channel: Mapped[str] = mapped_column(String(20), index=True)  # organic | instagram | website
    date: Mapped[date] = mapped_column(Date, index=True)
    sessions: Mapped[int | None] = mapped_column(BigInteger)
    users: Mapped[int | None] = mapped_column(BigInteger)
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    engagement: Mapped[int | None] = mapped_column(BigInteger)
    followers: Mapped[int | None] = mapped_column(BigInteger)
    conversions: Mapped[int | None] = mapped_column(BigInteger)
    revenue_minor: Mapped[int | None] = mapped_column(BigInteger)
    avg_position: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30))  # ga4 | search_console | instagram | demo


class Report(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "reports"

    name: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(10), default="pdf")  # pdf | csv
    sections: Mapped[list] = mapped_column(default=list)
    filters: Mapped[dict] = mapped_column(default=dict)  # date range, platforms, campaigns
    white_label: Mapped[bool] = mapped_column(default=False)
    schedule: Mapped[str] = mapped_column(String(20), default="once")  # once | weekly | monthly
    recipients: Mapped[list] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | ready | failed
    storage_key: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
