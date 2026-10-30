import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class MediaAsset(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "media_assets"

    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(30), default="creative")  # brand_logo | brand_asset | creative
    kind: Mapped[str] = mapped_column(String(20))  # image | video | document
    storage_key: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255), default="")
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None]
    height: Mapped[int | None]
    # upload | ai | offline_placeholder
    source: Mapped[str] = mapped_column(String(30), default="upload")
    prompt: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ContentAsset(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "content_assets"

    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300), default="Untitled")
    platform: Mapped[str] = mapped_column(String(30))  # instagram | facebook | blog | google_ads | ...
    format: Mapped[str] = mapped_column(String(30))  # post | carousel | reel | story | article | ...
    objective: Mapped[str | None] = mapped_column(String(50))
    language: Mapped[str] = mapped_column(String(10), default="en")
    # draft | in_review | approved | rejected | changes_requested
    status: Mapped[str] = mapped_column(String(30), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    generation_status: Mapped[str] = mapped_column(String(20), default="ready")  # pending | ready | failed
    generation_error: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(20))  # offline | openai
    body: Mapped[dict] = mapped_column(default=dict)  # mirrors the current version for quick reads
    brief: Mapped[dict] = mapped_column(default=dict)  # the generation inputs
    quality: Mapped[dict] = mapped_column(default=dict)  # latest rule-check result
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_runs.id", ondelete="SET NULL"))


class ContentVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "content_versions"
    __table_args__ = (UniqueConstraint("content_asset_id", "version"),)

    content_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_assets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(default=dict)
    source: Mapped[str] = mapped_column(String(20))  # ai | user | variation
    label: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ContentTemplate(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "content_templates"

    name: Mapped[str] = mapped_column(String(200))
    platform: Mapped[str] = mapped_column(String(30))
    format: Mapped[str] = mapped_column(String(30))
    body: Mapped[dict] = mapped_column(default=dict)


class SocialPost(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "social_posts"

    connected_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="SET NULL")
    )
    content_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_assets.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(String(30), default="instagram")
    format: Mapped[str] = mapped_column(String(20), default="image")  # image | carousel | reel | story
    caption: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[list] = mapped_column(default=list)  # [{"media_asset_id": ..., "url": ..., "kind": ...}]
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # draft | in_review | approved | scheduled | publishing | published | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(String(100))
    container_id: Mapped[str | None] = mapped_column(String(100))
    permalink: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    publish_log: Mapped[list] = mapped_column(default=list)  # recorded platform responses
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(default=dict)  # latest insights from the platform
    metrics_source: Mapped[str | None] = mapped_column(String(20))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
