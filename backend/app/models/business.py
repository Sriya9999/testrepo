import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class Brand(IdMixin, TimestampMixin, TenantMixin, Base):
    """Brand memory: retrieved before any generation so output follows the brand."""

    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    website_url: Mapped[str | None] = mapped_column(String(500))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    colors: Mapped[list] = mapped_column(default=list)  # ["#0F172A", ...]
    fonts: Mapped[list] = mapped_column(default=list)
    target_customers: Mapped[str] = mapped_column(Text, default="")
    products: Mapped[list] = mapped_column(default=list)  # [{"name": ..., "description": ...}]
    voice: Mapped[str] = mapped_column(Text, default="")
    competitor_references: Mapped[list] = mapped_column(default=list)
    prohibited_claims: Mapped[list] = mapped_column(default=list)
    approved_ctas: Mapped[list] = mapped_column(default=list)
    locations: Mapped[list] = mapped_column(default=list)
    languages: Mapped[list] = mapped_column(default=lambda: ["en"])
    is_default: Mapped[bool] = mapped_column(default=False)


class Client(IdMixin, TimestampMixin, Base):
    """An agency's client. The client's data lives in its own workspace (client_workspace_id)."""

    __tablename__ = "clients"

    agency_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    client_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(120))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | paused | archived
    account_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Website(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "websites"

    domain: Mapped[str] = mapped_column(String(255))
    business_category: Mapped[str | None] = mapped_column(String(120))
    target_country: Mapped[str | None] = mapped_column(String(2))
    target_location: Mapped[str | None] = mapped_column(String(200))
    primary_language: Mapped[str] = mapped_column(String(10), default="en")
    search_console_property: Mapped[str | None] = mapped_column(String(300))
    analytics_property: Mapped[str | None] = mapped_column(String(100))
    latest_score: Mapped[int | None]


class Competitor(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "competitors"

    website_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list] = mapped_column(default=list)
