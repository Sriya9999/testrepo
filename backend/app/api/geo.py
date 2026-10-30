import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.brands import brand_context
from app.db import as_aware, utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.engines import geo_analysis
from app.errors import AppError, IntegrationRequired, PaymentRequired
from app.models import GeoProject, GeoPrompt, GeoResult, Job, SeoAudit, SeoIssue, Website
from app.providers import geo as geo_providers
from app.providers.ai import get_ai
from app.services import accounts, audit, credits, jobs
from app.services.accounts import default_brand

router = APIRouter(tags=["geo"])


class CompetitorRef(BaseModel):
    name: str
    domain: str | None = None
    aliases: list[str] = []


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand_name: str = Field(min_length=1, max_length=200)
    brand_aliases: list[str] = []
    domain: str | None = None
    competitors: list[CompetitorRef] = []
    providers: list[str] = ["openai_search", "perplexity"]
    schedule: Literal["off", "daily", "weekly"] = "weekly"


class ProjectPatch(BaseModel):
    name: str | None = None
    brand_aliases: list[str] | None = None
    domain: str | None = None
    competitors: list[CompetitorRef] | None = None
    providers: list[str] | None = None
    schedule: Literal["off", "daily", "weekly"] | None = None


class PromptIn(BaseModel):
    project_id: uuid.UUID
    text: str = Field(min_length=3, max_length=1000)
    category: Literal["industry", "local", "comparison", "purchase", "informational"] = "informational"
    location: str | None = None
    source: Literal["user", "ai_suggested"] = "user"


class PromptsBulkIn(BaseModel):
    project_id: uuid.UUID
    prompts: list[PromptIn] = []


class SuggestIn(BaseModel):
    project_id: uuid.UUID


class RunIn(BaseModel):
    project_id: uuid.UUID
    prompt_ids: list[uuid.UUID] | None = None
    providers: list[str] | None = None


class ManualIn(BaseModel):
    prompt_id: uuid.UUID
    engine: Literal["google_ai_overview", "copilot", "chatgpt", "perplexity", "gemini", "other"]
    response_text: str = Field(min_length=1, max_length=50_000)
    citations: list[str] = []


def project_out(p: GeoProject, prompt_count: int | None = None) -> dict:
    return {"id": str(p.id), "name": p.name, "brand_name": p.brand_name, "brand_aliases": p.brand_aliases, "domain": p.domain,
            "competitors": p.competitors, "providers": p.providers, "schedule": p.schedule, "last_run_at": p.last_run_at,
            "prompt_count": prompt_count, "created_at": p.created_at}


def result_out(r: GeoResult, prompt_text: str | None = None) -> dict:
    return {"id": str(r.id), "prompt_id": str(r.prompt_id), "prompt": prompt_text, "provider": r.provider, "status": r.status,
            "response_text": r.response_text, "citations": r.citations, "brand_mentioned": r.brand_mentioned,
            "brand_cited": r.brand_cited, "brand_position": r.brand_position, "competitor_mentions": r.competitor_mentions,
            "sentiment": r.sentiment, "error": r.error, "observed_at": r.observed_at, "run_batch_id": str(r.run_batch_id) if r.run_batch_id else None}


@router.get("/geo/providers")
def providers(ctx: Ctx):
    avail = geo_providers.available()
    return [{"id": k, **v, "available": avail.get(k, False)} for k, v in geo_providers.PROVIDERS.items()]


@router.post("/geo/projects", status_code=201)
def create_project(body: ProjectIn, db: DB, ctx: WorkspaceContext = require("geo:write")):
    unknown = set(body.providers) - set(geo_providers.PROVIDERS)
    if unknown:
        raise AppError(f"Unknown providers: {', '.join(unknown)}")
    p = GeoProject(workspace_id=ctx.workspace_id, name=body.name, brand_name=body.brand_name, brand_aliases=body.brand_aliases,
                   domain=body.domain, competitors=[c.model_dump() for c in body.competitors], providers=body.providers,
                   schedule=body.schedule)
    db.add(p)
    audit.record(db, "geo.project_created", ctx=ctx, resource_type="geo_project", resource_id=p.id)
    db.commit()
    return project_out(p, 0)


@router.get("/geo/projects")
def list_projects(ctx: Ctx, db: DB):
    ctx.require("geo:read")
    out = []
    for p in db.scalars(select(GeoProject).where(GeoProject.workspace_id == ctx.workspace_id).order_by(GeoProject.created_at)):
        count = db.scalar(select(func.count()).select_from(GeoPrompt).where(GeoPrompt.project_id == p.id)) or 0
        out.append(project_out(p, count))
    return out


@router.patch("/geo/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch, db: DB, ctx: WorkspaceContext = require("geo:write")):
    p = get_or_404(db, GeoProject, project_id, ctx, "GEO project")
    changes = body.model_dump(exclude_unset=True)
    if "competitors" in changes:
        changes["competitors"] = [c if isinstance(c, dict) else c.model_dump() for c in changes["competitors"]]
    for k, v in changes.items():
        setattr(p, k, v)
    db.commit()
    return project_out(p)


def _add_prompt(db: Session, ctx, body: PromptIn) -> GeoPrompt:
    get_or_404(db, GeoProject, body.project_id, ctx, "GEO project")
    count = db.scalar(select(func.count()).select_from(GeoPrompt).where(GeoPrompt.workspace_id == ctx.workspace_id)) or 0
    accounts.check_limit(db, ctx.workspace, "geo_prompts", count)
    prompt = GeoPrompt(workspace_id=ctx.workspace_id, project_id=body.project_id, text=body.text.strip(), category=body.category,
                       location=body.location, source=body.source)
    db.add(prompt)
    db.flush()
    return prompt


def prompt_out(q: GeoPrompt) -> dict:
    return {"id": str(q.id), "project_id": str(q.project_id), "text": q.text, "category": q.category, "location": q.location,
            "active": q.active, "source": q.source, "created_at": q.created_at}


@router.post("/geo/prompts", status_code=201)
def add_prompt(body: PromptIn, db: DB, ctx: WorkspaceContext = require("geo:write")):
    q = _add_prompt(db, ctx, body)
    db.commit()
    return prompt_out(q)


@router.post("/geo/prompts/bulk", status_code=201)
def add_prompts(body: PromptsBulkIn, db: DB, ctx: WorkspaceContext = require("geo:write")):
    out = [prompt_out(_add_prompt(db, ctx, PromptIn(**{**p.model_dump(), "project_id": body.project_id}))) for p in body.prompts]
    db.commit()
    return out


@router.get("/geo/prompts")
def list_prompts(ctx: Ctx, db: DB, project_id: uuid.UUID | None = None, category: str | None = None):
    ctx.require("geo:read")
    stmt = select(GeoPrompt).where(GeoPrompt.workspace_id == ctx.workspace_id)
    if project_id:
        stmt = stmt.where(GeoPrompt.project_id == project_id)
    if category:
        stmt = stmt.where(GeoPrompt.category == category)
    prompts = db.scalars(stmt.order_by(GeoPrompt.created_at)).all()
    latest: dict = {}
    for r in db.scalars(select(GeoResult).where(GeoResult.prompt_id.in_([q.id for q in prompts]), GeoResult.status == "completed")
                        .order_by(GeoResult.observed_at)):
        latest.setdefault(r.prompt_id, {})[r.provider] = {"mentioned": r.brand_mentioned, "cited": r.brand_cited,
                                                          "position": r.brand_position, "observed_at": r.observed_at}
    return [{**prompt_out(q), "latest": latest.get(q.id, {})} for q in prompts]


@router.patch("/geo/prompts/{prompt_id}")
def update_prompt(prompt_id: str, body: dict, db: DB, ctx: WorkspaceContext = require("geo:write")):
    q = get_or_404(db, GeoPrompt, prompt_id, ctx, "Prompt")
    for k in ("text", "category", "location", "active"):
        if k in body:
            setattr(q, k, body[k])
    db.commit()
    return prompt_out(q)


@router.delete("/geo/prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: str, db: DB, ctx: WorkspaceContext = require("geo:write")):
    db.delete(get_or_404(db, GeoPrompt, prompt_id, ctx, "Prompt"))
    db.commit()


@router.post("/geo/prompts/suggest")
def suggest(body: SuggestIn, db: DB, ctx: WorkspaceContext = require("geo:write")):
    p = get_or_404(db, GeoProject, body.project_id, ctx, "GEO project")
    credits.ensure_affordable(db, ctx.workspace_id, [("geo_prompt_discovery", 1)])
    brand = default_brand(db, ctx.workspace_id)
    b = brand_context(brand)
    products = [x.get("name", "") for x in b.get("products", []) if isinstance(x, dict)]
    location = (b.get("locations") or [None])[0]
    comps = [c["name"] for c in p.competitors]

    def offline():
        return {"prompts": geo_analysis.suggest_prompts(p.brand_name, b.get("industry") or ctx.workspace.industry or "business",
                                                        products, location, comps, b.get("target_customers", ""))}
    out = get_ai().json_task(
        "geo_prompts", "Suggest 12 realistic questions people ask AI assistants when looking for this kind of business. "
        "Mix categories: industry, local, comparison, purchase, informational.",
        {"BRAND": b, "COMPETITORS": comps, "LOCATION": location},
        {"type": "object", "properties": {"prompts": {"type": "array", "items": {"type": "object", "properties": {
            "category": {"type": "string"}, "text": {"type": "string"}, "location": {"type": ["string", "null"]}}}}}},
        offline)
    existing = {q.text.lower() for q in db.scalars(select(GeoPrompt).where(GeoPrompt.project_id == p.id))}
    suggestions = [s for s in out.get("prompts", []) if s.get("text", "").lower() not in existing]
    credits.charge(db, ctx.workspace_id, "geo_prompt_discovery", reference=str(p.id), actor_id=ctx.user.id)
    db.commit()
    return {"suggestions": suggestions}


def _providers_for(project: GeoProject, requested: list[str] | None) -> list[str]:
    avail = geo_providers.available()
    wanted = requested or project.providers
    return [p for p in wanted if avail.get(p)]


@router.post("/geo/monitoring/run", status_code=202)
def run_monitoring(body: RunIn, db: DB, ctx: WorkspaceContext = require("geo:write")):
    p = get_or_404(db, GeoProject, body.project_id, ctx, "GEO project")
    providers_ = _providers_for(p, body.providers)
    if not providers_:
        raise IntegrationRequired("No AI search provider API is configured (OpenAI or Perplexity). "
                                  "You can still paste observed answers with manual import.")
    stmt = select(GeoPrompt).where(GeoPrompt.project_id == p.id, GeoPrompt.active.is_(True))
    if body.prompt_ids:
        stmt = stmt.where(GeoPrompt.id.in_(body.prompt_ids))
    prompt_ids = [str(q.id) for q in db.scalars(stmt)]
    if not prompt_ids:
        raise AppError("Add at least one active prompt first.")
    estimate = credits.ensure_affordable(db, ctx.workspace_id, [("geo_prompt_query", len(prompt_ids) * len(providers_))])
    job = jobs.enqueue(db, "geo.monitor", {"project_id": p.id, "prompt_ids": prompt_ids, "providers": providers_},
                       workspace_id=ctx.workspace_id, created_by=ctx.user.id, max_attempts=1)
    db.commit()
    return {"job_id": str(job.id), "queries": len(prompt_ids) * len(providers_), "estimated_credits": estimate}


def _store_result(db: Session, p: GeoProject, prompt: GeoPrompt, provider: str, text: str, citations: list[dict],
                  batch: uuid.UUID | None) -> GeoResult:
    a = geo_analysis.analyze(text, citations, p.brand_name, p.brand_aliases, p.domain, p.competitors)
    for c in citations:
        c["domain"] = geo_analysis.domain_of(c.get("url", ""))
    r = GeoResult(workspace_id=p.workspace_id, project_id=p.id, prompt_id=prompt.id, run_batch_id=batch, provider=provider,
                  response_text=text, citations=citations, brand_mentioned=a["brand_mentioned"], brand_cited=a["brand_cited"],
                  brand_position=a["brand_position"], competitor_mentions=a["competitor_mentions"], sentiment=a["sentiment"],
                  observed_at=utcnow())
    db.add(r)
    return r


@jobs.handler("geo.monitor")
def _job_monitor(db: Session, job: Job) -> dict:
    p = db.get(GeoProject, uuid.UUID(job.payload["project_id"]))
    batch = uuid.uuid4()
    done = failed = 0
    stopped = None
    for pid in job.payload["prompt_ids"]:
        prompt = db.get(GeoPrompt, uuid.UUID(pid))
        if prompt is None:
            continue
        for provider in job.payload["providers"]:
            try:
                text, cites = geo_providers.ask(provider, prompt.text, prompt.location)
            except Exception as exc:  # noqa: BLE001 - recorded per query, other queries continue
                db.add(GeoResult(workspace_id=p.workspace_id, project_id=p.id, prompt_id=prompt.id, run_batch_id=batch,
                                 provider=provider, status="failed", error=str(exc)[:1000], observed_at=utcnow()))
                db.commit()
                failed += 1
                continue
            r = _store_result(db, p, prompt, provider, text, cites, batch)
            try:
                credits.charge(db, p.workspace_id, "geo_prompt_query", reference=str(batch), actor_id=job.created_by,
                               description=f"GEO query on {provider}")
            except PaymentRequired:
                db.expunge(r)
                db.rollback()
                stopped = "Out of credits"
                break
            db.commit()
            done += 1
        if stopped:
            break
    p.last_run_at = utcnow()
    db.commit()
    return {"completed": done, "failed": failed, "batch": str(batch), "stopped": stopped}


@router.post("/geo/results/manual", status_code=201)
def manual_result(body: ManualIn, db: DB, ctx: WorkspaceContext = require("geo:write")):
    """Record an answer observed in an engine without an API (e.g. Google AI Overviews)."""
    prompt = get_or_404(db, GeoPrompt, body.prompt_id, ctx, "Prompt")
    p = db.get(GeoProject, prompt.project_id)
    r = _store_result(db, p, prompt, f"manual:{body.engine}", body.response_text,
                      [{"url": u, "title": None} for u in body.citations if u.strip()], None)
    db.commit()
    return result_out(r, prompt.text)


@router.get("/geo/results")
def results(ctx: Ctx, db: DB, project_id: uuid.UUID | None = None, prompt_id: uuid.UUID | None = None,
            provider: str | None = None, limit: int = 100):
    ctx.require("geo:read")
    stmt = select(GeoResult, GeoPrompt.text).join(GeoPrompt, GeoPrompt.id == GeoResult.prompt_id).where(
        GeoResult.workspace_id == ctx.workspace_id)
    if project_id:
        stmt = stmt.where(GeoResult.project_id == project_id)
    if prompt_id:
        stmt = stmt.where(GeoResult.prompt_id == prompt_id)
    if provider:
        stmt = stmt.where(GeoResult.provider == provider)
    return [result_out(r, text) for r, text in db.execute(stmt.order_by(GeoResult.observed_at.desc()).limit(min(limit, 500)))]


def _project_results(db: Session, p: GeoProject, days: int) -> list[GeoResult]:
    since = utcnow() - timedelta(days=days)
    return db.scalars(select(GeoResult).where(GeoResult.project_id == p.id, GeoResult.observed_at >= since)).all()


@router.get("/geo/visibility")
def visibility(ctx: Ctx, db: DB, project_id: uuid.UUID, days: int = 30):
    ctx.require("geo:read")
    p = get_or_404(db, GeoProject, project_id, ctx, "GEO project")
    rows = _project_results(db, p, days)
    names = [c["name"] for c in p.competitors]
    by_provider: dict = {}
    for r in rows:
        by_provider.setdefault(r.provider, []).append(r)
    history: dict = {}
    for r in rows:
        history.setdefault(as_aware(r.observed_at).date().isoformat(), []).append(r)
    return {
        "project": project_out(p), "days": days, "overall": geo_analysis.visibility(rows, names),
        "by_provider": {k: geo_analysis.visibility(v, names) for k, v in by_provider.items()},
        "history": [{"date": d, **{k: v for k, v in geo_analysis.visibility(rs, names).items()
                                   if k in ("geo_score", "mention_rate", "citation_rate", "share_of_voice")}}
                    for d, rs in sorted(history.items())],
        "score_note": "GEO score is a MarketingOS indicator combining mention rate, citation rate, share of voice, "
                      "position and sentiment. It is not an official metric of any AI provider.",
    }


@router.get("/geo/competitors")
def competitor_visibility(ctx: Ctx, db: DB, project_id: uuid.UUID, days: int = 30):
    ctx.require("geo:read")
    p = get_or_404(db, GeoProject, project_id, ctx, "GEO project")
    v = geo_analysis.visibility(_project_results(db, p, days), [c["name"] for c in p.competitors])
    brand_row = {"name": p.brand_name, "is_brand": True, "mention_rate": v.get("mention_rate"), "share_of_voice": v.get("share_of_voice")}
    return {"rows": [brand_row] + [{**c, "is_brand": False} for c in v.get("competitors", [])],
            "top_cited_domains": v.get("top_cited_domains", [])}


@router.get("/geo/recommendations")
def geo_recommendations(ctx: Ctx, db: DB, project_id: uuid.UUID, days: int = 30):
    ctx.require("geo:read")
    p = get_or_404(db, GeoProject, project_id, ctx, "GEO project")
    rows = _project_results(db, p, days)
    prompts = {q.id: q.text for q in db.scalars(select(GeoPrompt).where(GeoPrompt.project_id == p.id))}
    has_sd = None
    if p.domain:
        site = db.scalar(select(Website).where(Website.workspace_id == ctx.workspace_id, Website.domain == p.domain.lower()))
        if site:
            latest = db.scalar(select(SeoAudit).where(SeoAudit.website_id == site.id, SeoAudit.status == "completed")
                               .order_by(SeoAudit.created_at.desc()))
            if latest:
                has_sd = db.scalar(select(SeoIssue).where(SeoIssue.audit_id == latest.id,
                                                          SeoIssue.code == "no_structured_data")) is None
    return {"recommendations": geo_analysis.recommendations(rows, prompts, p.brand_name, has_sd),
            "note": None if rows else "Run monitoring (or import answers) to get recommendations."}


def enqueue_scheduled_monitoring(db: Session) -> int:
    count = 0
    now = utcnow()
    for p in db.scalars(select(GeoProject).where(GeoProject.schedule != "off")):
        due = timedelta(days=1 if p.schedule == "daily" else 7)
        if p.last_run_at and as_aware(p.last_run_at) > now - due:
            continue
        providers_ = _providers_for(p, None)
        prompt_ids = [str(q.id) for q in db.scalars(select(GeoPrompt).where(GeoPrompt.project_id == p.id, GeoPrompt.active.is_(True)))]
        if not providers_ or not prompt_ids:
            continue
        need = credits.estimate(db, [("geo_prompt_query", len(prompt_ids) * len(providers_))])
        if credits.get_wallet(db, p.workspace_id).balance < need:
            continue
        p.last_run_at = now  # claim this slot even if the job later fails
        jobs.enqueue(db, "geo.monitor", {"project_id": p.id, "prompt_ids": prompt_ids, "providers": providers_},
                     workspace_id=p.workspace_id, max_attempts=1)
        count += 1
    db.commit()
    return count
