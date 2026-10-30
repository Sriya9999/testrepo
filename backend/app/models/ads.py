import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class AdAccount(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "ad_accounts"
    __table_args__ = (UniqueConstraint("workspace_id", "platform", "external_id"),)

    connected_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE")
    )
    platform: Mapped[str] = mapped_column(String(20))  # meta | google
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    timezone: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="active")
    details: Mapped[dict] = mapped_column(default=dict)  # pages, instagram identities, ...


class Campaign(IdMixin, TimestampMixin, TenantMixin, Base):
    """A Meta or Google Ads campaign. Drafts hold their full structure in `config`;
    nothing reaches the ad platform until an approval for exactly this config is granted."""

    __tablename__ = "campaigns"

    platform: Mapped[str] = mapped_column(String(20), index=True)  # meta | google
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ad_accounts.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(300))
    objective: Mapped[str] = mapped_column(String(40))
    # draft | pending_approval | approved | submitting | active | paused | failed | archived
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    daily_budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    lifetime_budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    config: Mapped[dict] = mapped_column(default=dict)
    external_id: Mapped[str | None] = mapped_column(String(64))
    external_status: Mapped[str | None] = mapped_column(String(40))
    submission_log: Mapped[list] = mapped_column(default=list)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by_ai: Mapped[bool] = mapped_column(default=False)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdEntity(IdMixin, TimestampMixin, TenantMixin, Base):
    """Ad sets / ad groups, ads and creatives created on or synced from the platform."""

    __tablename__ = "ad_entities"

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(20))  # ad_set | ad_group | ad | creative
    external_id: Mapped[str | None] = mapped_column(String(64))
    parent_external_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str | None] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(default=dict)


class AdInsight(IdMixin, TimestampMixin, TenantMixin, Base):
    """Daily performance rows as reported by the ad platform (or flagged demo data)."""

    __tablename__ = "ad_insights"
    __table_args__ = (UniqueConstraint("campaign_id", "entity_external_id", "date"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    entity_level: Mapped[str] = mapped_column(String(20), default="campaign")  # campaign | ad
    entity_external_id: Mapped[str] = mapped_column(String(64), default="")
    entity_name: Mapped[str] = mapped_column(String(300), default="")
    date: Mapped[date] = mapped_column(Date, index=True)
    impressions: Mapped[int] = mapped_column(BigInteger, default=0)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0)
    spend_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    leads: Mapped[int] = mapped_column(BigInteger, default=0)
    purchases: Mapped[int] = mapped_column(BigInteger, default=0)
    conversions: Mapped[int] = mapped_column(BigInteger, default=0)
    revenue_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    search_impression_share: Mapped[float | None] = mapped_column(Numeric(6, 4))
    source: Mapped[str] = mapped_column(String(20))  # meta | google | demo
    raw: Mapped[dict] = mapped_column(default=dict)
    note: Mapped[str | None] = mapped_column(Text)
