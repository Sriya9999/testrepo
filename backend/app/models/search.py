import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, IdMixin, TenantMixin, TimestampMixin


class SeoAudit(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "seo_audits"

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | completed | failed
    config: Mapped[dict] = mapped_column(default=dict)  # max_pages, include_pagespeed, ...
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    score: Mapped[int | None]
    summary: Mapped[dict] = mapped_column(default=dict)  # issue counts, site-level checks, performance
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeoPage(IdMixin, TimestampMixin, Base):
    __tablename__ = "seo_pages"

    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seo_audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    status_code: Mapped[int | None]
    data: Mapped[dict] = mapped_column(default=dict)


class SeoIssue(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "seo_issues"

    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seo_audits.id", ondelete="CASCADE"), index=True)
    page_url: Mapped[str | None] = mapped_column(String(2000))
    category: Mapped[str] = mapped_column(String(20))  # technical | on_page | content | performance
    severity: Mapped[str] = mapped_column(String(10))  # critical | high | medium | low
    code: Mapped[str] = mapped_column(String(60), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(default=dict)


class Keyword(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("workspace_id", "website_id", "text", "country"),)

    website_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2), default="IN")
    language: Mapped[str] = mapped_column(String(10), default="en")
    # Metrics come only from a connected data provider; null means "not measured".
    search_volume: Mapped[int | None] = mapped_column(BigInteger)
    difficulty: Mapped[int | None]
    cpc_minor: Mapped[int | None] = mapped_column(BigInteger)
    cpc_currency: Mapped[str | None] = mapped_column(String(3))
    competition: Mapped[str | None] = mapped_column(String(20))
    metrics_source: Mapped[str | None] = mapped_column(String(30))
    metrics_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intent: Mapped[str | None] = mapped_column(String(20))  # rule-based estimate
    cluster: Mapped[str | None] = mapped_column(String(200))
    tracked: Mapped[bool] = mapped_column(default=True)


class KeywordRanking(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "keyword_rankings"
    __table_args__ = (UniqueConstraint("keyword_id", "date", "source"),)

    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    position: Mapped[float | None] = mapped_column(Float)
    clicks: Mapped[int | None]
    impressions: Mapped[int | None]
    url: Mapped[str | None] = mapped_column(String(2000))
    source: Mapped[str] = mapped_column(String(30))  # search_console | demo


class GeoProject(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "geo_projects"

    name: Mapped[str] = mapped_column(String(200))
    brand_name: Mapped[str] = mapped_column(String(200))
    brand_aliases: Mapped[list] = mapped_column(default=list)
    domain: Mapped[str | None] = mapped_column(String(255))
    competitors: Mapped[list] = mapped_column(default=list)  # [{"name": ..., "domain": ..., "aliases": [...]}]
    providers: Mapped[list] = mapped_column(default=lambda: ["openai_search", "perplexity"])
    schedule: Mapped[str] = mapped_column(String(20), default="weekly")  # off | daily | weekly
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeoPrompt(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "geo_prompts"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geo_projects.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # industry | local | comparison | purchase | informational
    category: Mapped[str] = mapped_column(String(20), default="informational")
    location: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(20), default="user")  # user | ai_suggested


class GeoResult(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "geo_results"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geo_projects.id", ondelete="CASCADE"), index=True)
    prompt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geo_prompts.id", ondelete="CASCADE"), index=True)
    run_batch_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(String(30))  # openai_search | perplexity | manual:<engine>
    status: Mapped[str] = mapped_column(String(20), default="completed")  # completed | failed
    response_text: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(default=list)  # [{"url": ..., "title": ..., "domain": ...}]
    brand_mentioned: Mapped[bool] = mapped_column(default=False)
    brand_cited: Mapped[bool] = mapped_column(default=False)
    brand_position: Mapped[int | None]  # 1 = first brand named in the answer
    competitor_mentions: Mapped[dict] = mapped_column(default=dict)  # {"Competitor": count}
    sentiment: Mapped[float | None] = mapped_column(Float)  # -1..1 around brand mentions
    error: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
