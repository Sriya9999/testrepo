import uuid
from datetime import date, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.engines import keywords as kw_engine
from app.engines import seo_crawler, seo_rules
from app.errors import AppError
from app.models import Competitor, Job, Keyword, KeywordRanking, PerformanceSnapshot, SeoAudit, SeoIssue, SeoPage, Website, Workspace
from app.providers import keyword_data
from app.services import accounts, audit, jobs

router = APIRouter(tags=["seo"])


class WebsiteIn(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    business_category: str | None = None
    target_country: str | None = Field(default="IN", max_length=2)
    target_location: str | None = None
    primary_language: str = "en"
    search_console_property: str | None = None
    analytics_property: str | None = None
    competitors: list[str] = []


class WebsitePatch(BaseModel):
    business_category: str | None = None
    target_country: str | None = None
    target_location: str | None = None
    primary_language: str | None = None
    search_console_property: str | None = None
    analytics_property: str | None = None


class AuditIn(BaseModel):
    website_id: uuid.UUID
    max_pages: int = Field(default=50, ge=1, le=500)
    include_pagespeed: bool = True
    competitor_id: uuid.UUID | None = None


class KeywordsIn(BaseModel):
    website_id: uuid.UUID | None = None
    keywords: list[str] = Field(min_length=1, max_length=500)
    country: str = "IN"
    language: str = "en"


class CompetitorIn(BaseModel):
    website_id: uuid.UUID | None = None
    name: str
    domain: str | None = None
    aliases: list[str] = []


def _clean_domain(domain: str) -> str:
    d = domain.strip().lower()
    for prefix in ("https://", "http://"):
        d = d.removeprefix(prefix)
    return d.split("/")[0]


def website_out(db: Session, w: Website) -> dict:
    latest = _latest_audit(db, w.id, None)
    comps = db.scalars(select(Competitor).where(Competitor.website_id == w.id))
    return {
        "id": str(w.id), "domain": w.domain, "business_category": w.business_category, "target_country": w.target_country,
        "target_location": w.target_location, "primary_language": w.primary_language,
        "search_console_property": w.search_console_property, "analytics_property": w.analytics_property,
        "latest_score": w.latest_score, "last_audit_at": latest.finished_at if latest else None,
        "competitors": [{"id": str(c.id), "name": c.name, "domain": c.domain} for c in comps],
    }


@router.post("/seo/websites", status_code=201)
def add_website(body: WebsiteIn, db: DB, ctx: WorkspaceContext = require("seo:write")):
    w = Website(workspace_id=ctx.workspace_id, domain=_clean_domain(body.domain), business_category=body.business_category,
                target_country=(body.target_country or "").upper() or None, target_location=body.target_location,
                primary_language=body.primary_language, search_console_property=body.search_console_property,
                analytics_property=body.analytics_property)
    db.add(w)
    db.flush()
    for c in body.competitors:
        db.add(Competitor(workspace_id=ctx.workspace_id, website_id=w.id, name=_clean_domain(c), domain=_clean_domain(c)))
    audit.record(db, "seo.website_added", ctx=ctx, resource_type="website", resource_id=w.id, data={"domain": w.domain})
    db.commit()
    return website_out(db, w)


@router.get("/seo/websites")
def list_websites(ctx: Ctx, db: DB):
    ctx.require("seo:read")
    return [website_out(db, w) for w in db.scalars(select(Website).where(Website.workspace_id == ctx.workspace_id).order_by(Website.created_at))]


@router.patch("/seo/websites/{website_id}")
def update_website(website_id: str, body: WebsitePatch, db: DB, ctx: WorkspaceContext = require("seo:write")):
    w = get_or_404(db, Website, website_id, ctx, "Website")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.commit()
    return website_out(db, w)


@router.post("/seo/competitors", status_code=201)
def add_competitor(body: CompetitorIn, db: DB, ctx: WorkspaceContext = require("seo:write")):
    if body.website_id:
        get_or_404(db, Website, body.website_id, ctx, "Website")
    c = Competitor(workspace_id=ctx.workspace_id, website_id=body.website_id, name=body.name,
                   domain=_clean_domain(body.domain) if body.domain else None, aliases=body.aliases)
    db.add(c)
    db.commit()
    return {"id": str(c.id), "name": c.name, "domain": c.domain, "aliases": c.aliases}


@router.post("/seo/audits", status_code=202)
def start_audit(body: AuditIn, db: DB, ctx: WorkspaceContext = require("seo:write")):
    w = get_or_404(db, Website, body.website_id, ctx, "Website")
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(SeoAudit).where(SeoAudit.workspace_id == ctx.workspace_id,
                                                                      SeoAudit.created_at >= month_start)) or 0
    accounts.check_limit(db, ctx.workspace, "seo_audits_per_month", used)
    plan = accounts.plan_for_workspace(db, ctx.workspace)
    max_pages = min(body.max_pages, (plan.limits or {}).get("crawl_pages", 500) if plan else 500, get_settings().crawler_max_pages * 10)
    config = {"max_pages": max_pages, "include_pagespeed": body.include_pagespeed, "domain": w.domain}
    if body.competitor_id:
        comp = get_or_404(db, Competitor, body.competitor_id, ctx, "Competitor")
        if not comp.domain:
            raise AppError("This competitor has no domain to audit.")
        config.update({"competitor_id": str(comp.id), "domain": comp.domain, "max_pages": min(max_pages, 20)})
    a = SeoAudit(workspace_id=ctx.workspace_id, website_id=w.id, config=config)
    db.add(a)
    db.flush()
    job = jobs.enqueue(db, "seo.audit", {"audit_id": a.id}, workspace_id=ctx.workspace_id, created_by=ctx.user.id, max_attempts=1)
    db.commit()
    return {"audit_id": str(a.id), "job_id": str(job.id), "status": a.status}


def audit_out(a: SeoAudit) -> dict:
    return {"id": str(a.id), "website_id": str(a.website_id), "status": a.status, "config": a.config,
            "pages_crawled": a.pages_crawled, "progress": a.progress, "score": a.score, "summary": a.summary,
            "error": a.error, "started_at": a.started_at, "finished_at": a.finished_at, "created_at": a.created_at,
            "competitor_id": (a.config or {}).get("competitor_id")}


@router.get("/seo/audits")
def list_audits(ctx: Ctx, db: DB, website_id: uuid.UUID | None = None):
    ctx.require("seo:read")
    stmt = select(SeoAudit).where(SeoAudit.workspace_id == ctx.workspace_id)
    if website_id:
        stmt = stmt.where(SeoAudit.website_id == website_id)
    return [audit_out(a) for a in db.scalars(stmt.order_by(SeoAudit.created_at.desc()).limit(50))]


@router.get("/seo/audits/{audit_id}")
def get_audit(audit_id: str, ctx: Ctx, db: DB, severity: str | None = None, category: str | None = None):
    ctx.require("seo:read")
    a = get_or_404(db, SeoAudit, audit_id, ctx, "Audit")
    stmt = select(SeoIssue).where(SeoIssue.audit_id == a.id)
    if severity:
        stmt = stmt.where(SeoIssue.severity == severity)
    if category:
        stmt = stmt.where(SeoIssue.category == category)
    issues = db.scalars(stmt).all()
    issue_dicts = [{"id": str(i.id), "code": i.code, "category": i.category, "severity": i.severity, "message": i.message,
                    "page_url": i.page_url, "details": i.details} for i in issues]
    issue_dicts.sort(key=lambda i: seo_rules.SEVERITY_ORDER[i["severity"]])
    pages = db.scalars(select(SeoPage).where(SeoPage.audit_id == a.id)).all()
    return {**audit_out(a), "issues": issue_dicts,
            "recommendations": seo_rules.recommendations([{**i, "page_url": i["page_url"]} for i in issue_dicts]),
            "pages": [{"url": p.url, "status_code": p.status_code, "title": p.data.get("title"),
                       "word_count": p.data.get("word_count"), "elapsed_ms": p.data.get("elapsed_ms")} for p in pages]}


def run_audit(db: Session, audit_id: uuid.UUID) -> dict:
    a = db.get(SeoAudit, audit_id)
    w = db.get(Website, a.website_id)
    a.status, a.started_at = "running", utcnow()
    db.commit()
    s = get_settings()

    def progress(done: int, total: int) -> None:
        a.pages_crawled, a.progress = done, min(95, round(done * 90 / max(total, 1)))
        db.commit()

    result = seo_crawler.crawl(a.config["domain"], a.config["max_pages"], s.crawler_timeout_seconds, s.crawler_user_agent, progress)
    perf = seo_crawler.pagespeed(result.start_url, s.pagespeed_api_key) if a.config.get("include_pagespeed") else None
    tracked = [k.text for k in db.scalars(select(Keyword).where(Keyword.website_id == w.id, Keyword.tracked.is_(True)))]
    is_competitor = bool(a.config.get("competitor_id"))
    issues = seo_rules.issues_from_crawl(result, perf, None if is_competitor else tracked,
                                         None if is_competitor else w.target_location)
    for p in result.pages:
        db.add(SeoPage(audit_id=a.id, url=p.url[:2000], status_code=p.status, data=p.to_dict()))
    for i in issues:
        db.add(SeoIssue(workspace_id=a.workspace_id, audit_id=a.id, page_url=(i["page_url"] or None), category=i["category"],
                        severity=i["severity"], code=i["code"], message=i["message"], details=i["details"]))
    a.score = seo_rules.score(issues, len(result.pages))
    a.pages_crawled = len(result.pages)
    a.summary = {**seo_rules.summary(issues), "robots": result.robots, "sitemap": result.sitemap, "https": result.https,
                 "performance": perf, "blocked": len(result.blocked),
                 "home": result.pages[0].to_dict() if result.pages else None}
    a.status, a.progress, a.finished_at = "completed", 100, utcnow()
    if not is_competitor:
        w.latest_score = a.score
    db.commit()
    return {"score": a.score, "issues": len(issues), "pages": len(result.pages)}


@jobs.handler("seo.audit")
def _job_audit(db: Session, job: Job) -> dict:
    return run_audit(db, uuid.UUID(job.payload["audit_id"]))


@jobs.on_failure("seo.audit")
def _job_audit_failed(db: Session, job: Job, message: str) -> None:
    a = db.get(SeoAudit, uuid.UUID(job.payload["audit_id"]))
    if a is not None:
        a.status, a.error, a.finished_at = "failed", message.split("\n")[0][:1000], utcnow()


# ---- keywords ---------------------------------------------------------------------------

def _latest_rankings(db: Session, keyword_ids: list[uuid.UUID]) -> dict:
    out: dict = {}
    if not keyword_ids:
        return out
    for r in db.scalars(select(KeywordRanking).where(KeywordRanking.keyword_id.in_(keyword_ids)).order_by(KeywordRanking.date)):
        prev = out.get(r.keyword_id, {})
        out[r.keyword_id] = {"position": r.position, "previous": prev.get("position"), "date": r.date, "url": r.url,
                             "clicks": r.clicks, "impressions": r.impressions, "source": r.source}
    return out


def keyword_out(k: Keyword, rank: dict | None) -> dict:
    change = None
    if rank and rank.get("position") is not None and rank.get("previous") is not None:
        change = round(rank["previous"] - rank["position"], 1)  # positive = moved up
    return {"id": str(k.id), "text": k.text, "country": k.country, "language": k.language,
            "website_id": str(k.website_id) if k.website_id else None, "search_volume": k.search_volume,
            "difficulty": k.difficulty, "cpc_minor": k.cpc_minor, "cpc_currency": k.cpc_currency, "competition": k.competition,
            "metrics_source": k.metrics_source, "metrics_updated_at": k.metrics_updated_at,
            "intent": k.intent, "intent_source": "rule_based_estimate", "cluster": k.cluster,
            "position": rank.get("position") if rank else None, "position_change": change,
            "ranking_url": rank.get("url") if rank else None, "ranking_source": rank.get("source") if rank else None}


@router.get("/seo/keywords")
def list_keywords(ctx: Ctx, db: DB, website_id: uuid.UUID | None = None):
    ctx.require("seo:read")
    stmt = select(Keyword).where(Keyword.workspace_id == ctx.workspace_id)
    if website_id:
        stmt = stmt.where(Keyword.website_id == website_id)
    rows = db.scalars(stmt.order_by(Keyword.cluster, Keyword.text)).all()
    ranks = _latest_rankings(db, [k.id for k in rows])
    return {"keywords": [keyword_out(k, ranks.get(k.id)) for k in rows],
            "metrics_provider": keyword_data.available_source(db, ctx.workspace_id),
            "note": None if keyword_data.available_source(db, ctx.workspace_id) else
            "Connect Google Ads (Keyword Planner) or configure DataForSEO to see search volume, difficulty and CPC."}


@router.post("/seo/keywords", status_code=201)
def add_keywords(body: KeywordsIn, db: DB, ctx: WorkspaceContext = require("seo:write")):
    if body.website_id:
        get_or_404(db, Website, body.website_id, ctx, "Website")
    from app.services.accounts import default_brand

    brand = default_brand(db, ctx.workspace_id)
    brand_terms = [brand.name] if brand else []
    added = []
    for text in {t.strip().lower() for t in body.keywords if t.strip()}:
        exists = db.scalar(select(Keyword).where(Keyword.workspace_id == ctx.workspace_id, Keyword.website_id == body.website_id,
                                                 Keyword.text == text, Keyword.country == body.country.upper()))
        if exists:
            continue
        k = Keyword(workspace_id=ctx.workspace_id, website_id=body.website_id, text=text[:300], country=body.country.upper(),
                    language=body.language, intent=kw_engine.intent(text, brand_terms))
        db.add(k)
        added.append(k)
    db.flush()
    recluster(db, ctx.workspace_id)
    job = None
    if added and keyword_data.available_source(db, ctx.workspace_id):
        job = jobs.enqueue(db, "seo.keyword_metrics", {"keyword_ids": [str(k.id) for k in added]}, workspace_id=ctx.workspace_id)
    db.commit()
    return {"added": len(added), "metrics_job_id": str(job.id) if job else None}


def recluster(db: Session, workspace_id: uuid.UUID) -> None:
    rows = db.scalars(select(Keyword).where(Keyword.workspace_id == workspace_id)).all()
    mapping = {}
    for name, members in kw_engine.cluster([k.text for k in rows]).items():
        for m in members:
            mapping[m] = name
    for k in rows:
        k.cluster = mapping.get(k.text)


@router.delete("/seo/keywords/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: str, db: DB, ctx: WorkspaceContext = require("seo:write")):
    db.delete(get_or_404(db, Keyword, keyword_id, ctx, "Keyword"))
    db.commit()


@router.post("/seo/keywords/refresh", status_code=202)
def refresh_keywords(db: DB, ctx: WorkspaceContext = require("seo:write")):
    if not keyword_data.available_source(db, ctx.workspace_id):
        from app.errors import IntegrationRequired

        raise IntegrationRequired("Connect Google Ads or configure DataForSEO to fetch keyword metrics.")
    ids = [str(k.id) for k in db.scalars(select(Keyword).where(Keyword.workspace_id == ctx.workspace_id))]
    job = jobs.enqueue(db, "seo.keyword_metrics", {"keyword_ids": ids}, workspace_id=ctx.workspace_id)
    db.commit()
    return {"job_id": str(job.id)}


@jobs.handler("seo.keyword_metrics")
def _job_keyword_metrics(db: Session, job: Job) -> dict:
    rows = [db.get(Keyword, uuid.UUID(i)) for i in job.payload["keyword_ids"]]
    rows = [r for r in rows if r is not None]
    by_country: dict[tuple, list[Keyword]] = {}
    for k in rows:
        by_country.setdefault((k.country, k.language), []).append(k)
    updated = 0
    ws = db.get(Workspace, job.workspace_id)
    for (country, language), group in by_country.items():
        source, metrics = keyword_data.fetch_metrics(db, job.workspace_id, [k.text for k in group], country, language)
        for k in group:
            m = metrics.get(k.text.lower())
            if not m:
                continue
            k.search_volume, k.cpc_minor, k.competition, k.difficulty = m["search_volume"], m["cpc_minor"], m["competition"], m["difficulty"]
            k.cpc_currency, k.metrics_source, k.metrics_updated_at = ws.currency, source, utcnow()
            updated += 1
    db.commit()
    return {"updated": updated}


@router.get("/seo/rankings")
def rankings(ctx: Ctx, db: DB, keyword_id: uuid.UUID | None = None, website_id: uuid.UUID | None = None, days: int = 90):
    ctx.require("seo:read")
    since = date.today() - timedelta(days=days)
    stmt = select(KeywordRanking, Keyword).join(Keyword, Keyword.id == KeywordRanking.keyword_id).where(
        KeywordRanking.workspace_id == ctx.workspace_id, KeywordRanking.date >= since)
    if keyword_id:
        stmt = stmt.where(KeywordRanking.keyword_id == keyword_id)
    if website_id:
        stmt = stmt.where(Keyword.website_id == website_id)
    return [{"keyword_id": str(k.id), "keyword": k.text, "date": r.date, "position": r.position, "clicks": r.clicks,
             "impressions": r.impressions, "url": r.url, "source": r.source}
            for r, k in db.execute(stmt.order_by(KeywordRanking.date))]


@router.get("/seo/competitors")
def competitors(ctx: Ctx, db: DB, website_id: uuid.UUID | None = None):
    ctx.require("seo:read")
    stmt = select(Competitor).where(Competitor.workspace_id == ctx.workspace_id)
    if website_id:
        stmt = stmt.where(Competitor.website_id == website_id)
    out = []
    own = None
    if website_id:
        w = get_or_404(db, Website, website_id, ctx, "Website")
        own = _latest_audit(db, w.id, None)
    for c in db.scalars(stmt):
        a = _latest_audit(db, c.website_id, str(c.id)) if c.website_id else None
        out.append({"id": str(c.id), "name": c.name, "domain": c.domain, "aliases": c.aliases,
                    "latest_audit": _compare_row(a), "audit_id": str(a.id) if a else None})
    return {"own": _compare_row(own), "competitors": out}


def _latest_audit(db: Session, website_id, competitor_id: str | None) -> SeoAudit | None:
    for a in db.scalars(select(SeoAudit).where(SeoAudit.website_id == website_id, SeoAudit.status == "completed")
                        .order_by(SeoAudit.created_at.desc())):
        if (a.config or {}).get("competitor_id") == competitor_id:
            return a
    return None


def _compare_row(a: SeoAudit | None) -> dict | None:
    if a is None:
        return None
    home = (a.summary or {}).get("home") or {}
    perf = (a.summary or {}).get("performance") or {}
    return {"score": a.score, "pages_crawled": a.pages_crawled, "audited_at": a.finished_at,
            "issues": (a.summary or {}).get("by_severity", {}), "https": (a.summary or {}).get("https"),
            "sitemap_urls": ((a.summary or {}).get("sitemap") or {}).get("urls"),
            "home_title": home.get("title"), "home_word_count": home.get("word_count"),
            "structured_data": home.get("json_ld_types", []), "performance_score": perf.get("performance_score")}


@router.get("/seo/recommendations")
def seo_recommendations(ctx: Ctx, db: DB, website_id: uuid.UUID):
    ctx.require("seo:read")
    w = get_or_404(db, Website, website_id, ctx, "Website")
    a = _latest_audit(db, w.id, None)
    issues = []
    if a is not None:
        issues = [{"code": i.code, "category": i.category, "severity": i.severity, "page_url": i.page_url}
                  for i in db.scalars(select(SeoIssue).where(SeoIssue.audit_id == a.id))]
    kws = db.scalars(select(Keyword).where(Keyword.website_id == w.id)).all()
    ranks = _latest_rankings(db, [k.id for k in kws])
    kw_data = [{"text": k.text, "intent": k.intent, "position": (ranks.get(k.id) or {}).get("position")} for k in kws]
    recs = seo_rules.recommendations(issues, kw_data)
    return {"audit_id": str(a.id) if a else None, "recommendations": recs,
            "note": None if a else "Run an audit to get technical and on-page recommendations."}


@router.get("/seo/overview")
def seo_overview(ctx: Ctx, db: DB, website_id: uuid.UUID):
    ctx.require("seo:read")
    w = get_or_404(db, Website, website_id, ctx, "Website")
    history = [{"date": a.finished_at, "score": a.score} for a in db.scalars(
        select(SeoAudit).where(SeoAudit.website_id == w.id, SeoAudit.status == "completed").order_by(SeoAudit.created_at))
        if not (a.config or {}).get("competitor_id")]
    latest = _latest_audit(db, w.id, None)
    since = date.today() - timedelta(days=90)
    traffic = [{"date": s.date, "clicks": s.clicks, "impressions": s.impressions, "sessions": s.sessions,
                "avg_position": s.avg_position, "source": s.source}
               for s in db.scalars(select(PerformanceSnapshot).where(
                   PerformanceSnapshot.workspace_id == ctx.workspace_id, PerformanceSnapshot.channel == "organic",
                   PerformanceSnapshot.date >= since).order_by(PerformanceSnapshot.date))]
    kws = list_keywords(ctx, db, w.id)["keywords"]
    return {"website": website_out(db, w), "score": latest.score if latest else None,
            "score_note": "Internal health indicator from the latest audit, not a Google metric.",
            "issues": (latest.summary or {}).get("by_severity", {}) if latest else {}, "history": history,
            "organic_traffic": traffic, "top_keywords": sorted([k for k in kws if k["position"]], key=lambda k: k["position"])[:10],
            "keywords_tracked": len(kws), "latest_audit_id": str(latest.id) if latest else None}

