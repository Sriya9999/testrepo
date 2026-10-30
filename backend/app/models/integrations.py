import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class ConnectedAccount(IdMixin, TimestampMixin, TenantMixin, Base):
    """One external account connected to a workspace. Credentials live in OAuthToken
    and are never serialized to API responses."""

    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("workspace_id", "provider", "external_id"),)

    # instagram | meta | google_ads | google_analytics | search_console | wordpress | shopify
    provider: Mapped[str] = mapped_column(String(30), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(300), default="")
    mode: Mapped[str] = mapped_column(String(10), default="live")  # live | sandbox
    status: Mapped[str] = mapped_column(String(20), default="connected")  # connected | error | disconnected
    scopes: Mapped[list] = mapped_column(default=list)
    details: Mapped[dict] = mapped_column(default=dict)  # non-secret metadata (username, page id, ...)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class OAuthToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "oauth_tokens"

    connected_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE"), unique=True
    )
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationSyncLog(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "integration_sync_logs"

    connected_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(30))
    operation: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))  # success | error
    message: Mapped[str] = mapped_column(Text, default="")
    records: Mapped[int] = mapped_column(default=0)
