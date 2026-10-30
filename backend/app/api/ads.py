"""Meta Ads and Google Ads campaign management (PRD 5.4 / 5.6).

Drafts are free to edit. Launching, activating, increasing budgets and other material
changes to live campaigns are proposed as approvals; the platform is only called after a
human approves exactly that configuration, and never above the workspace spend cap.
"""

import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.brands import brand_context
from app.db import utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.engines import ads_optimizer, offline_writer
from app.engines import keywords as kw_engine
from app.engines.content_formats import check as content_check
from app.errors import AppError, Conflict, IntegrationRequired, NotFound
from app.models import AdAccount, AdEntity, AdInsight, Approval, Campaign, ConnectedAccount, Job, MediaAsset, User, Workspace
from app.providers import google, meta
from app.providers.ai import get_ai
from app.services import approvals, audit, credits, integrations, jobs, storage
from app.services.accounts import default_brand
from app.services.approvals import ActionSpec, register_action
from app.services.policy import max_daily_budget, requires_approval, workspace_settings

router = APIRouter(tags=["advertising"])

PLATFORMS = ("meta", "google")
Platform = Literal["meta", "google"]
EDITABLE = {"draft", "pending_approval", "changes_requested", "failed", "rejected"}
LIVE = {"active", "paused"}
META_CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "BOOK_TRAVEL", "CONTACT_US", "ORDER_NOW", "GET_OFFER", "SUBSCRIBE", "CALL_NOW"]


# ---- schemas --------------------------------------------------------------------------

class MetaAudience(BaseModel):
    age_min: int = Field(default=18, ge=13, le=65)
    age_max: int = Field(default=65, ge=13, le=65)
    genders: list[int] = []  # 1 = men, 2 = women, empty = all
    interests: list[dict] = []  # [{"id": "...", "name": "..."}] from Meta's targeting search
    custom_audience_ids: list[str] = []


class MetaGeo(BaseModel):
    countries: list[str] = ["IN"]
    cities: list[dict] = []  # [{"key": "...", "name": "...", "radius_km": 10}]


class MetaPlacements(BaseModel):
    automatic: bool = True
    publisher_platforms: list[str] = ["facebook", "instagram"]


class MetaCopy(BaseModel):
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    cta_type: str = "LEARN_MORE"
    link_url: str = ""


class MetaConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    audience: MetaAudience = MetaAudience()
    geo: MetaGeo = MetaGeo()
    placements: MetaPlacements = MetaPlacements()
    ad_copy: MetaCopy = Field(default_factory=MetaCopy, alias="copy")
    media_asset_ids: list[str] = []
    page_id: str | None = None
    instagram_user_id: str | None = None
    pixel_id: str | None = None


class GoogleKeyword(BaseModel):
    text: str
    match_type: Literal["BROAD", "PHRASE", "EXACT"] = "PHRASE"


class GoogleAdGroup(BaseModel):
    name: str
    keywords: list[GoogleKeyword] = []
    headlines: list[str] = []
    descriptions: list[str] = []
    final_url: str = ""
    paths: list[str] = []


class GoogleConfig(BaseModel):
    ad_groups: list[GoogleAdGroup] = []
    negative_keywords: list[str] = []
    locations: list[dict] = [{"id": "2356", "name": "India"}]  # geo target constants
    language_ids: list[str] = ["1000"]  # English
    bidding: Literal["maximize_clicks", "maximize_conversions", "manual_cpc"] = "maximize_clicks"
    search_partners: bool = False
    landing_page_recommendations: list[str] = []


class DraftIn(BaseModel):
    ad_account_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=300)
    objective: str = "traffic"
    daily_budget_minor: int | None = Field(default=None, gt=0)
    lifetime_budget_minor: int | None = Field(default=None, gt=0)
    start_date: date | None = None
    end_date: date | None = None
    config: dict = {}


class DraftPatch(BaseModel):
    ad_account_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=300)
    objective: str | None = None
    daily_budget_minor: int | None = Field(default=None, gt=0)
    lifetime_budget_minor: int | None = Field(default=None, gt=0)
    start_date: date | None = None
    end_date: date | None = None
    config: dict | None = None


class GenerateIn(BaseModel):
    ad_account_id: uuid.UUID | None = None
    objective: str = "traffic"
    product: str = ""
    audience: str = ""
    location: str | None = None
    website: str = ""
    keywords: list[str] = []
    daily_budget_minor: int = Field(gt=0)
    start_date: date | None = None
    end_date: date | None = None
    brand_id: uuid.UUID | None = None
    tone: str = ""


class LaunchIn(BaseModel):
    activate: bool = False
    note: str | None = None


def _parse_config(platform: str, raw: dict) -> dict:
    model = MetaConfig if platform == "meta" else GoogleConfig
    return model.model_validate(raw or {}).model_dump()


def _objectives(platform: str) -> list[str]:
    return list(meta.OBJECTIVES) if platform == "meta" else ["traffic", "leads", "sales"]


def campaign_state(c: Campaign) -> dict:
    """Everything an approval covers (status excluded: it changes as approvals move)."""
    return {
        "campaign_id": str(c.id), "platform": c.platform, "name": c.name, "objective": c.objective,
        "ad_account_id": str(c.ad_account_id) if c.ad_account_id else None, "currency": c.currency,
        "daily_budget_minor": c.daily_budget_minor, "lifetime_budget_minor": c.lifetime_budget_minor,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None, "config": c.config,
        "external_id": c.external_id,
    }


def campaign_out(db: Session, c: Campaign, detail: bool = False) -> dict:
    out = {**campaign_state(c), "id": str(c.id), "status": c.status, "external_status": c.external_status,
           "last_error": c.last_error, "created_by_ai": c.created_by_ai, "submitted_at": c.submitted_at,
           "last_synced_at": c.last_synced_at, "created_at": c.created_at, "updated_at": c.updated_at}
    since = date.today() - timedelta(days=30)
    rows = db.scalars(select(AdInsight).where(AdInsight.campaign_id == c.id, AdInsight.date >= since,
                                              AdInsight.entity_level == "campaign")).all()
    out["last_30_days"] = ads_optimizer.totals(rows) if rows else None
    out["metrics_source"] = sorted({r.source for r in rows}) if rows else []
    if detail:
        out["validation_errors"] = validate(db, c)
        out["entities"] = [{"level": e.level, "external_id": e.external_id, "name": e.name, "status": e.status}
                           for e in db.scalars(select(AdEntity).where(AdEntity.campaign_id == c.id))]
        out["approvals"] = [
            {"id": str(a.id), "action_type": a.action_type, "status": a.status, "title": a.title, "created_at": a.created_at,
             "decided_at": a.decided_at, "budget_impact_minor": a.budget_impact_minor}
            for a in db.scalars(select(Approval).where(Approval.resource_id == c.id).order_by(Approval.created_at.desc()))
        ]
        out["submission_log"] = c.submission_log
        out["approval_required_for_pause"] = requires_approval("pause_campaign", db.get(Workspace, c.workspace_id))
    return out


def validate(db: Session, c: Campaign) -> list[str]:
    errors: list[str] = []
    ws = db.get(Workspace, c.workspace_id)
    if not c.ad_account_id:
        errors.append("Choose an ad account.")
    else:
        acct = db.get(AdAccount, c.ad_account_id)
        if acct is None or acct.status != "active":
            errors.append("The ad account is disconnected.")
    if c.objective not in _objectives(c.platform):
        errors.append(f"Objective must be one of {', '.join(_objectives(c.platform))}.")
    if not c.daily_budget_minor and not c.lifetime_budget_minor:
        errors.append("Set a daily or lifetime budget.")
    if c.daily_budget_minor and c.daily_budget_minor > max_daily_budget(ws, c.platform):
        errors.append(f"Daily budget is above this workspace's limit of {max_daily_budget(ws, c.platform) / 100:,.0f} {c.currency}.")
    if c.lifetime_budget_minor and not c.end_date:
        errors.append("Lifetime budgets need an end date.")
    if c.start_date and c.end_date and c.end_date <= c.start_date:
        errors.append("End date must be after the start date.")
    if c.start_date and c.start_date < date.today() and c.status not in LIVE:
        errors.append("Start date is in the past.")
    cfg = c.config or {}
    if c.platform == "meta":
        copy = cfg.get("copy", {})
        if not copy.get("primary_text") or not copy.get("headline"):
            errors.append("Add primary text and a headline.")
        if not (copy.get("link_url") or "").startswith("http"):
            errors.append("Add the destination URL (https://...).")
        if copy.get("cta_type") not in META_CTAS:
            errors.append("Choose a supported call-to-action button.")
        if not cfg.get("media_asset_ids"):
            errors.append("Add an image or video for the ad.")
        if not cfg.get("page_id"):
            errors.append("Choose the Facebook Page the ad runs from.")
        aud = cfg.get("audience", {})
        if aud.get("age_min", 18) > aud.get("age_max", 65):
            errors.append("Minimum age is above maximum age.")
        if not (cfg.get("geo", {}).get("countries") or cfg.get("geo", {}).get("cities")):
            errors.append("Choose at least one location.")
        if c.objective == "sales" and not cfg.get("pixel_id"):
            errors.append("Sales campaigns need a Meta pixel to optimise for purchases.")
    else:
        groups = cfg.get("ad_groups") or []
        if not groups:
            errors.append("Add at least one ad group.")
        for g in groups:
            if not g.get("keywords"):
                errors.append(f"Ad group '{g.get('name')}' has no keywords.")
            if not (g.get("final_url") or "").startswith("http"):
                errors.append(f"Ad group '{g.get('name')}' needs a final URL.")
            result = content_check("google_ads", "search_ad", {"headlines": g.get("headlines", []), "descriptions": g.get("descriptions", [])})
            errors += [f"{g.get('name')}: {i['message']}" for i in result["issues"] if i["level"] == "error"]
        if not cfg.get("locations"):
            errors.append("Choose at least one location.")
    return errors


def _get_campaign(db: Session, ctx, platform: str, campaign_id: str) -> Campaign:
    c = get_or_404(db, Campaign, campaign_id, ctx, "Campaign")
    if c.platform != platform:
        raise NotFound("Campaign not found")
    return c


def _budget_impact(c: Campaign) -> int:
    if c.lifetime_budget_minor:
        return c.lifetime_budget_minor
    days = (c.end_date - (c.start_date or date.today())).days if c.end_date else 30
    return (c.daily_budget_minor or 0) * max(days, 1)


# ---- approval actions -----------------------------------------------------------------

def _launch_snapshot(db: Session, a: Approval) -> dict:
    return {"campaign": campaign_state(db.get(Campaign, a.resource_id)), "activate": a.payload.get("activate", False)}


def _launch_execute(db: Session, a: Approval, user: User) -> dict:
    c = db.get(Campaign, a.resource_id)
    errors = validate(db, c)
    if errors:
        raise AppError("The campaign is no longer valid: " + "; ".join(errors), code="campaign_invalid")
    c.status = "approved"
    job = jobs.enqueue(db, "ads.submit", {"campaign_id": c.id, "approval_id": a.id, "activate": a.payload.get("activate", False)},
                       workspace_id=c.workspace_id, max_attempts=3)
    return {"job_id": str(job.id), "campaign_status": "approved"}


def _launch_rejected(db: Session, a: Approval) -> None:
    c = db.get(Campaign, a.resource_id)
    if c is not None and c.status == "pending_approval":
        c.status = "changes_requested" if a.status == "changes_requested" else "draft"


def _change_snapshot(db: Session, a: Approval) -> dict:
    return {**a.payload, "base": campaign_state(db.get(Campaign, a.resource_id))}


def _change_execute(db: Session, a: Approval, user: User) -> dict:
    c = db.get(Campaign, a.resource_id)
    job = jobs.enqueue(db, "ads.update", {"campaign_id": c.id, "approval_id": a.id}, workspace_id=c.workspace_id)
    return {"job_id": str(job.id)}


register_action("launch_campaign", ActionSpec("ads:approve", _launch_execute, _launch_snapshot, _launch_rejected, "Launch campaign"))
for _act in ("activate_campaign", "pause_campaign", "increase_budget", "modify_campaign"):
    register_action(_act, ActionSpec("ads:approve", _change_execute, _change_snapshot, None, _act.replace("_", " ").capitalize()))


def request_launch(db: Session, c: Campaign, activate: bool, requested_by: uuid.UUID | None, agent: str | None = None,
                   group_id: uuid.UUID | None = None, reasoning: str | None = None) -> Approval:
    errors = validate(db, c)
    if errors:
        raise AppError("Fix these before requesting approval: " + "; ".join(errors), code="campaign_invalid",
                       details={"errors": errors})
    acct = db.get(AdAccount, c.ad_account_id)
    budget = (f"{c.daily_budget_minor / 100:,.0f} {c.currency}/day" if c.daily_budget_minor
              else f"{c.lifetime_budget_minor / 100:,.0f} {c.currency} lifetime")
    approval = approvals.request_approval(
        db, workspace_id=c.workspace_id, action_type="launch_campaign", resource_type="campaign", resource_id=c.id,
        title=f"{'Launch' if activate else 'Create (paused)'} {c.platform.title()} campaign '{c.name}' on {acct.name} · {budget}",
        payload={"campaign": campaign_state(c), "activate": activate}, platform=c.platform,
        budget_impact_minor=_budget_impact(c), currency=c.currency, requested_by=requested_by, requested_by_agent=agent,
        group_id=group_id, ai_reasoning=reasoning,
        expected_outcome=f"{c.objective.replace('_', ' ').title()} campaign created on {c.platform.title()}"
                         + (" and started." if activate else " in a paused state, ready to activate."),
    )
    c.status = "pending_approval"
    return approval


# ---- endpoints (shared by /ads/meta and /ads/google) -----------------------------------

def _register(platform: str) -> None:
    prefix = f"/ads/{platform}"

    @router.get(f"{prefix}/accounts", name=f"{platform}_accounts")
    def list_accounts(ctx: Ctx, db: DB):
        ctx.require("ads:read")
        rows = db.scalars(select(AdAccount).where(AdAccount.workspace_id == ctx.workspace_id, AdAccount.platform == platform))
        out = []
        for a in rows:
            conn = db.get(ConnectedAccount, a.connected_account_id)
            out.append({"id": str(a.id), "external_id": a.external_id, "name": a.name, "currency": a.currency,
                        "timezone": a.timezone, "status": a.status, "mode": conn.mode if conn else None,
                        "pages": (a.details or {}).get("pages", [])})
        return out

    @router.get(f"{prefix}/campaigns", name=f"{platform}_campaigns")
    def list_campaigns(ctx: Ctx, db: DB, status: str | None = None):
        ctx.require("ads:read")
        stmt = select(Campaign).where(Campaign.workspace_id == ctx.workspace_id, Campaign.platform == platform)
        if status:
            stmt = stmt.where(Campaign.status == status)
        return [campaign_out(db, c) for c in db.scalars(stmt.order_by(Campaign.updated_at.desc()))]

    @router.post(f"{prefix}/campaigns/drafts", status_code=201, name=f"{platform}_create_draft")
    def create_draft(body: DraftIn, db: DB, ctx: WorkspaceContext = require("ads:write")):
        c = Campaign(workspace_id=ctx.workspace_id, platform=platform, name=body.name, objective=body.objective,
                     daily_budget_minor=body.daily_budget_minor, lifetime_budget_minor=body.lifetime_budget_minor,
                     start_date=body.start_date, end_date=body.end_date, config=_parse_config(platform, body.config),
                     created_by=ctx.user.id, currency=ctx.workspace.currency)
        if body.ad_account_id:
            acct = get_or_404(db, AdAccount, body.ad_account_id, ctx, "Ad account")
            c.ad_account_id, c.currency = acct.id, acct.currency
        db.add(c)
        db.flush()
        audit.record(db, "campaign.draft_created", ctx=ctx, resource_type="campaign", resource_id=c.id)
        db.commit()
        return campaign_out(db, c, detail=True)

    @router.post(f"{prefix}/campaigns/generate", status_code=201, name=f"{platform}_generate")
    def generate_draft(body: GenerateIn, db: DB, ctx: WorkspaceContext = require("ads:write")):
        credits.ensure_affordable(db, ctx.workspace_id, [("campaign_draft", 1)])
        c = build_ai_draft(db, ctx.workspace_id, platform, body, ctx.user.id)
        credits.charge(db, ctx.workspace_id, "campaign_draft", reference=str(c.id), actor_id=ctx.user.id,
                       description=f"AI {platform} campaign draft")
        db.commit()
        return campaign_out(db, c, detail=True)

    @router.get(f"{prefix}/campaigns/{{campaign_id}}", name=f"{platform}_campaign")
    def get_campaign(campaign_id: str, ctx: Ctx, db: DB):
        ctx.require("ads:read")
        return campaign_out(db, _get_campaign(db, ctx, platform, campaign_id), detail=True)

    @router.patch(f"{prefix}/campaigns/{{campaign_id}}", name=f"{platform}_update")
    def update_campaign(campaign_id: str, body: DraftPatch, db: DB, ctx: WorkspaceContext = require("ads:write")):
        c = _get_campaign(db, ctx, platform, campaign_id)
        changes = body.model_dump(exclude_unset=True)
        if "config" in changes:
            changes["config"] = _parse_config(platform, {**(c.config or {}), **(changes["config"] or {})})
        if c.status in EDITABLE:
            if "ad_account_id" in changes and changes["ad_account_id"]:
                acct = get_or_404(db, AdAccount, changes["ad_account_id"], ctx, "Ad account")
                c.currency = acct.currency
            for k, v in changes.items():
                setattr(c, k, v)
            if c.status == "pending_approval":
                for a in db.scalars(select(Approval).where(Approval.resource_id == c.id, Approval.status == "pending")):
                    a.status = "superseded"
                c.status = "draft"
            db.commit()
            return {"applied": True, "campaign": campaign_out(db, c, detail=True)}
        if c.status not in LIVE:
            raise Conflict(f"A campaign that is {c.status} cannot be edited right now.")
        result = propose_live_change(db, ctx, c, changes)
        db.commit()
        return {**result, "campaign": campaign_out(db, c, detail=True)}

    @router.post(f"{prefix}/campaigns/{{campaign_id}}/request-approval", name=f"{platform}_request_approval")
    def request_approval_ep(campaign_id: str, body: LaunchIn, db: DB, ctx: WorkspaceContext = require("ads:write")):
        c = _get_campaign(db, ctx, platform, campaign_id)
        if c.status not in EDITABLE:
            raise Conflict(f"This campaign is {c.status}.")
        approval = request_launch(db, c, body.activate, ctx.user.id)
        db.commit()
        return {"approval_id": str(approval.id), "status": c.status}

    @router.post(f"{prefix}/campaigns/{{campaign_id}}/submit", name=f"{platform}_submit")
    def submit(campaign_id: str, db: DB, ctx: WorkspaceContext = require("ads:write")):
        """Submit an approved campaign to the platform (also retries a failed submission)."""
        c = _get_campaign(db, ctx, platform, campaign_id)
        approval = db.scalar(select(Approval).where(Approval.resource_id == c.id, Approval.action_type == "launch_campaign")
                             .order_by(Approval.created_at.desc()))
        if approval is None or approval.status not in ("approved", "failed", "executed"):
            raise Conflict("This campaign has not been approved. Request approval first.", code="approval_required")
        if approval.status == "executed" and c.external_id:
            raise Conflict("This campaign was already submitted.")
        if approvals.payload_hash(_launch_snapshot(db, approval)) != approval.payload_hash:
            raise Conflict("The campaign changed after it was approved. Request approval again.", code="approval_stale")
        c.status = "approved"
        approval.status = "approved"
        job = jobs.enqueue(db, "ads.submit", {"campaign_id": c.id, "approval_id": approval.id,
                                              "activate": approval.payload.get("activate", False)}, workspace_id=ctx.workspace_id)
        db.commit()
        return {"job_id": str(job.id), "status": c.status}

    @router.post(f"{prefix}/campaigns/{{campaign_id}}/pause", name=f"{platform}_pause")
    def pause(campaign_id: str, db: DB, ctx: WorkspaceContext = require("ads:write")):
        c = _get_campaign(db, ctx, platform, campaign_id)
        if c.status != "active":
            raise Conflict("Only active campaigns can be paused.")
        return _status_change(db, ctx, c, "pause_campaign", "PAUSED")

    @router.post(f"{prefix}/campaigns/{{campaign_id}}/activate", name=f"{platform}_activate")
    def activate(campaign_id: str, db: DB, ctx: WorkspaceContext = require("ads:write")):
        c = _get_campaign(db, ctx, platform, campaign_id)
        if c.status != "paused":
            raise Conflict("Only paused campaigns can be activated.")
        return _status_change(db, ctx, c, "activate_campaign", "ACTIVE")

    @router.post(f"{prefix}/campaigns/{{campaign_id}}/duplicate", status_code=201, name=f"{platform}_duplicate")
    def duplicate(campaign_id: str, db: DB, ctx: WorkspaceContext = require("ads:write")):
        src = _get_campaign(db, ctx, platform, campaign_id)
        c = Campaign(workspace_id=ctx.workspace_id, platform=platform, name=f"{src.name} (copy)"[:300], objective=src.objective,
                     ad_account_id=src.ad_account_id, currency=src.currency, daily_budget_minor=src.daily_budget_minor,
                     lifetime_budget_minor=src.lifetime_budget_minor, config=src.config, created_by=ctx.user.id)
        db.add(c)
        db.commit()
        return campaign_out(db, c, detail=True)

    @router.get(f"{prefix}/insights", name=f"{platform}_insights")
    def insights(ctx: Ctx, db: DB, campaign_id: uuid.UUID | None = None, start: date | None = None, end: date | None = None):
        ctx.require("ads:read")
        end = end or date.today()
        start = start or end - timedelta(days=29)
        stmt = select(AdInsight).where(AdInsight.workspace_id == ctx.workspace_id, AdInsight.platform == platform,
                                       AdInsight.entity_level == "campaign", AdInsight.date >= start, AdInsight.date <= end)
        if campaign_id:
            stmt = stmt.where(AdInsight.campaign_id == campaign_id)
        rows = db.scalars(stmt).all()
        campaigns = {c.id: c for c in db.scalars(select(Campaign).where(Campaign.workspace_id == ctx.workspace_id))}
        by_c: dict = {}
        for r in rows:
            by_c.setdefault(r.campaign_id, []).append(r)
        return {
            "range": {"start": start, "end": end}, "currency": ctx.workspace.currency,
            "totals": ads_optimizer.totals(rows), "daily": ads_optimizer.daily_series(rows),
            "campaigns": [{"campaign_id": str(cid), "name": campaigns[cid].name if cid in campaigns else "", **ads_optimizer.totals(rs)}
                          for cid, rs in by_c.items()],
            "sources": sorted({r.source for r in rows}),
            "provenance": {"measured": ["impressions", "reach", "clicks", "spend_minor", "leads", "purchases", "conversions", "revenue_minor"],
                           "calculated": ["ctr", "cpc_minor", "cpm_minor", "cpl_minor", "cpa_minor", "roas", "frequency"]},
        }

    @router.get(f"{prefix}/recommendations", name=f"{platform}_recommendations")
    def recommendations(ctx: Ctx, db: DB, days: int = 30):
        ctx.require("ads:read")
        since = date.today() - timedelta(days=days)
        rows = db.scalars(select(AdInsight).where(AdInsight.workspace_id == ctx.workspace_id, AdInsight.platform == platform,
                                                  AdInsight.entity_level == "campaign", AdInsight.date >= since)).all()
        campaigns = {c.id: c for c in db.scalars(select(Campaign).where(Campaign.workspace_id == ctx.workspace_id))}
        recs = ads_optimizer.analyze(rows, campaigns, ctx.workspace.currency)
        return {"recommendations": recs, "based_on_rows": len(rows), "sources": sorted({r.source for r in rows}),
                "note": None if rows else "No synced performance data yet. Recommendations appear after campaigns run and sync."}

    @router.post(f"{prefix}/sync", status_code=202, name=f"{platform}_sync")
    def sync(db: DB, ctx: WorkspaceContext = require("ads:read")):
        ids = []
        for a in db.scalars(select(AdAccount).where(AdAccount.workspace_id == ctx.workspace_id, AdAccount.platform == platform,
                                                    AdAccount.status == "active")):
            ids.append(str(jobs.enqueue(db, "ads.sync", {"ad_account_id": a.id, "days": 30}, workspace_id=ctx.workspace_id).id))
        db.commit()
        return {"job_ids": ids}


for _p in PLATFORMS:
    _register(_p)


def _status_change(db: Session, ctx, c: Campaign, action: str, target: str) -> dict:
    payload = {"campaign_id": str(c.id), "operation": "set_status", "status": target}
    if requires_approval(action, ctx.workspace):
        payload["base"] = campaign_state(c)
        approval = approvals.request_approval(
            db, workspace_id=ctx.workspace_id, action_type=action, resource_type="campaign", resource_id=c.id,
            title=f"{'Pause' if target == 'PAUSED' else 'Activate'} campaign '{c.name}'", payload=payload,
            platform=c.platform, requested_by=ctx.user.id,
            budget_impact_minor=(c.daily_budget_minor or 0) * 30 if target == "ACTIVE" else None, currency=c.currency,
            expected_outcome="Delivery " + ("stops." if target == "PAUSED" else "resumes at the approved budget."))
        db.commit()
        return {"requires_approval": True, "approval_id": str(approval.id)}
    job = jobs.enqueue(db, "ads.update", {"campaign_id": c.id, "direct": payload}, workspace_id=ctx.workspace_id)
    audit.record(db, f"campaign.{target.lower()}", ctx=ctx, resource_type="campaign", resource_id=c.id)
    db.commit()
    return {"requires_approval": False, "job_id": str(job.id)}


def propose_live_change(db: Session, ctx, c: Campaign, changes: dict) -> dict:
    """Split a change to a live campaign into what can apply now and what needs approval."""
    changes = {k: v for k, v in changes.items() if getattr(c, k, None) != v}
    if not changes:
        return {"applied": False, "message": "Nothing changed."}
    unsupported = set(changes) - {"name", "daily_budget_minor", "lifetime_budget_minor", "end_date", "config"}
    if unsupported:
        raise AppError(f"These can't change on a live campaign: {', '.join(sorted(unsupported))}. Duplicate it instead.")
    if "config" in changes:
        old, new = c.config or {}, changes["config"]
        changed_keys = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
        allowed = {"audience", "geo", "placements", "negative_keywords"}
        if changed_keys - allowed:
            raise AppError("Creative, copy and keyword structure can't change on a live campaign. Duplicate it and launch the new version.")
    ws = ctx.workspace
    if changes.get("daily_budget_minor") and changes["daily_budget_minor"] > max_daily_budget(ws, c.platform):
        raise AppError("That budget is above the workspace's daily spend limit.")
    if "name" in changes:
        c.name = changes.pop("name")
    if not changes:
        return {"applied": True}
    budget_up = (changes.get("daily_budget_minor") or 0) > (c.daily_budget_minor or 0) or \
                (changes.get("lifetime_budget_minor") or 0) > (c.lifetime_budget_minor or 0)
    budget_only = set(changes) <= {"daily_budget_minor", "lifetime_budget_minor"}
    if budget_only and not budget_up and not workspace_settings(ws)["approvals"]["require_approval_for_budget_decrease"]:
        job = jobs.enqueue(db, "ads.update", {"campaign_id": c.id, "direct": {"operation": "update", "changes": _jsonable(changes)}},
                           workspace_id=ctx.workspace_id)
        audit.record(db, "campaign.budget_decreased", ctx=ctx, resource_type="campaign", resource_id=c.id, data=_jsonable(changes))
        return {"applied": True, "job_id": str(job.id)}
    action = "increase_budget" if budget_up and budget_only else "modify_campaign"
    new_daily = changes.get("daily_budget_minor", c.daily_budget_minor) or 0
    approval = approvals.request_approval(
        db, workspace_id=ctx.workspace_id, action_type=action, resource_type="campaign", resource_id=c.id,
        title=(f"Increase budget of '{c.name}' to {new_daily / 100:,.0f} {c.currency}/day" if action == "increase_budget"
               else f"Change live campaign '{c.name}': {', '.join(sorted(changes))}"),
        payload={"campaign_id": str(c.id), "operation": "update", "changes": _jsonable(changes), "base": campaign_state(c)},
        platform=c.platform,
        budget_impact_minor=(new_daily - (c.daily_budget_minor or 0)) * 30 if "daily_budget_minor" in changes else None,
        currency=c.currency, requested_by=ctx.user.id,
        expected_outcome="The live campaign is updated on the platform after approval.")
    return {"applied": False, "requires_approval": True, "approval_id": str(approval.id)}


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in d.items()}


# ---- AI draft builder (Meta Ads Agent / SEM Agent) -------------------------------------

def build_ai_draft(db: Session, workspace_id: uuid.UUID, platform: str, body: GenerateIn, actor_id: uuid.UUID | None,
                   ai_run_id: uuid.UUID | None = None) -> Campaign:
    from app.models import Brand

    brand = db.get(Brand, body.brand_id) if body.brand_id else default_brand(db, workspace_id)
    bctx = brand_context(brand)
    product = body.product or ((bctx.get("products") or [{}])[0].get("name") if bctx.get("products") else "") or bctx.get("name", "")
    website = body.website or bctx.get("website_url") or ""
    ws = db.get(Workspace, workspace_id)
    acct = None
    if body.ad_account_id:
        acct = db.get(AdAccount, body.ad_account_id)
        if acct is None or acct.workspace_id != workspace_id:
            raise NotFound("Ad account not found")
    else:
        acct = db.scalar(select(AdAccount).where(AdAccount.workspace_id == workspace_id, AdAccount.platform == platform,
                                                 AdAccount.status == "active"))
    budget = min(body.daily_budget_minor, max_daily_budget(ws, platform))
    brief = {"product": product, "audience": body.audience, "objective": body.objective, "tone": body.tone,
             "keywords": body.keywords, "location": body.location, "cta": (bctx.get("approved_ctas") or ["Learn more"])[0]}
    ai = get_ai()
    if platform == "meta":
        def offline():
            ad = offline_writer.write("facebook", "ad", brief, bctx)
            return {"copy": {"primary_text": ad["primary_text"], "headline": ad["headline"], "description": ad["description"]},
                    "age_min": 18, "age_max": 55, "reasoning": "Broad audience with automatic placements lets Meta's delivery "
                    "find the cheapest results while the campaign learns; narrow after 1–2 weeks of data."}
        out = ai.json_task("meta_campaign", "Draft a Meta ads campaign. Suggest copy and an audience age range; explain your reasoning.",
                           {"BRAND": bctx, "BRIEF": brief, "WEBSITE": website},
                           {"type": "object", "properties": {"copy": {"type": "object"}, "age_min": {"type": "integer"},
                                                             "age_max": {"type": "integer"}, "reasoning": {"type": "string"}}},
                           offline)
        pages = (acct.details or {}).get("pages", []) if acct else []
        config = MetaConfig(
            audience=MetaAudience(age_min=out.get("age_min", 18), age_max=out.get("age_max", 55)),
            geo=MetaGeo(countries=["IN"], cities=[{"name": body.location, "radius_km": 15}] if body.location else []),
            copy=MetaCopy(**{**out.get("copy", {}), "link_url": website, "cta_type": "LEARN_MORE" if body.objective != "sales" else "SHOP_NOW"}),
            page_id=pages[0]["id"] if pages else None,
            instagram_user_id=(pages[0].get("instagram_user_id") if pages else None),
        ).model_dump()
        config["ai_reasoning"] = out.get("reasoning")
    else:
        seeds = body.keywords or [k for k in [product, *(p.get("name", "") for p in bctx.get("products", []))] if k]
        candidates = kw_engine.expand_seeds(seeds[:5], body.location)
        clusters = kw_engine.cluster(candidates)
        c_ctx = offline_writer._ctx(brief, bctx)

        def offline():
            groups = []
            for name, members in list(clusters.items())[:5]:
                ad = offline_writer.search_ad({**c_ctx, "product": name.title(), "keywords": [name]}, None)
                match = lambda k: "EXACT" if len(k.split()) >= 3 else "PHRASE"  # noqa: E731
                groups.append({"name": name.title(), "keywords": [{"text": k, "match_type": match(k)} for k in members
                                                                   if kw_engine.intent(k) != "informational"] or
                               [{"text": name, "match_type": "PHRASE"}],
                               "headlines": ad["headlines"], "descriptions": ad["descriptions"],
                               "final_url": website, "paths": ad["paths"]})
            return {"ad_groups": groups, "reasoning": "One ad group per keyword theme keeps ads relevant to each search; "
                    "informational searches are left out because they rarely convert."}
        out = ai.json_task("google_campaign", "Draft a Google search campaign: ad groups with keywords (match types), "
                           "15 headlines (<=30 chars) and 4 descriptions (<=90 chars) each.",
                           {"BRAND": bctx, "BRIEF": brief, "WEBSITE": website, "KEYWORD_THEMES": clusters},
                           {"type": "object", "properties": {"ad_groups": {"type": "array"}, "reasoning": {"type": "string"}}},
                           offline)
        config = GoogleConfig(
            ad_groups=[GoogleAdGroup.model_validate(g) for g in out.get("ad_groups", [])],
            negative_keywords=kw_engine.NEGATIVE_SUGGESTIONS[:10],
            landing_page_recommendations=[website] if website else [],
        ).model_dump()
        config["ai_reasoning"] = out.get("reasoning")
    c = Campaign(
        workspace_id=workspace_id, platform=platform, ad_account_id=acct.id if acct else None,
        name=f"{product or 'Campaign'} · {body.objective.title()} · {date.today():%b %Y}"[:300], objective=body.objective,
        currency=acct.currency if acct else ws.currency, daily_budget_minor=budget, start_date=body.start_date,
        end_date=body.end_date, config=config, created_by_ai=True, created_by=actor_id, ai_run_id=ai_run_id,
    )
    db.add(c)
    db.flush()
    return c


# ---- background jobs ------------------------------------------------------------------

def _log(c: Campaign, event: str, data: dict | None = None) -> None:
    c.submission_log = [*(c.submission_log or []), {"at": utcnow().isoformat(), "event": event, **(data or {})}][-50:]


def _client_for(db: Session, acct: AdAccount):
    conn = db.get(ConnectedAccount, acct.connected_account_id)
    if conn is None or conn.status == "disconnected":
        raise IntegrationRequired("The ad account is disconnected.")
    if conn.mode == "sandbox":
        return None
    token = integrations.access_token(db, conn)
    return meta.MetaClient(token) if acct.platform == "meta" else google.GoogleAdsClient(token)


@jobs.handler("ads.submit")
def _job_submit(db: Session, job: Job) -> dict:
    c = db.get(Campaign, uuid.UUID(job.payload["campaign_id"]))
    approval = db.get(Approval, uuid.UUID(job.payload["approval_id"]))
    if approval is None or approval.status != "approved":
        raise AppError("Submission refused: no granted approval.")
    if approvals.payload_hash(_launch_snapshot(db, approval)) != approval.payload_hash:
        c.status = "draft"
        approval.status = "superseded"
        db.commit()
        return {"refused": "campaign changed after approval"}
    ws = db.get(Workspace, c.workspace_id)
    if c.daily_budget_minor and c.daily_budget_minor > max_daily_budget(ws, c.platform):
        raise AppError("Daily budget exceeds the workspace spend limit.")
    acct = db.get(AdAccount, c.ad_account_id)
    activate = bool(job.payload.get("activate"))
    c.status = "submitting"
    client = _client_for(db, acct)
    db.commit()
    if client is None:
        ext = f"sandbox_cmp_{uuid.uuid4().hex[:10]}"
        _log(c, "sandbox_submit", {"note": "Recorded locally; nothing was sent to the ad platform.", "activate": activate})
        db.add(AdEntity(workspace_id=c.workspace_id, campaign_id=c.id, level="ad_set" if c.platform == "meta" else "ad_group",
                        external_id=f"{ext}_set", parent_external_id=ext, name=f"{c.name} · set", status="PAUSED"))
    elif c.platform == "meta":
        ext = _submit_meta(db, c, acct, client, activate)
    else:
        ext = _submit_google(db, c, acct, client, activate)
    c.external_id = ext
    c.status = "active" if activate else "paused"
    c.external_status = "ACTIVE" if activate else "PAUSED"
    c.submitted_at = utcnow()
    c.last_error = None
    approvals.mark_execution(db, approval.id, True, {"external_id": ext, "activated": activate})
    audit.record(db, "campaign.submitted", workspace_id=c.workspace_id, actor_type="system", resource_type="campaign",
                 resource_id=c.id, data={"external_id": ext, "activate": activate, "approval_id": str(approval.id)})
    db.commit()
    return {"external_id": ext}


@jobs.on_failure("ads.submit")
def _job_submit_failed(db: Session, job: Job, message: str) -> None:
    c = db.get(Campaign, uuid.UUID(job.payload["campaign_id"]))
    if c is not None and c.status in ("approved", "submitting"):
        c.status = "failed"
        c.last_error = message.split("\n")[0][:1000]
        _log(c, "error", {"message": c.last_error})
    approvals.mark_execution(db, job.payload.get("approval_id"), False, {"error": message.split("\n")[0][:500]})


def _submit_meta(db: Session, c: Campaign, acct: AdAccount, client: meta.MetaClient, activate: bool) -> str:
    cfg = c.config
    act = acct.external_id
    image_hash = None
    media_ids = cfg.get("media_asset_ids") or []
    if media_ids:
        media = db.get(MediaAsset, uuid.UUID(media_ids[0]))
        if media and media.kind == "image":
            image_hash = client.upload_image(act, media.filename or "creative.jpg", storage.read_bytes(media.storage_key))
    cid = client.create_campaign(act, c.name, c.objective, c.daily_budget_minor, c.lifetime_budget_minor)
    _log(c, "campaign_created", {"id": cid})
    db.commit()
    aud, geo, plc = cfg["audience"], cfg["geo"], cfg["placements"]
    targeting = {"age_min": aud["age_min"], "age_max": aud["age_max"], "geo_locations": {"countries": geo.get("countries", [])}}
    if geo.get("cities"):
        targeting["geo_locations"]["cities"] = [{"key": x["key"], "radius": x.get("radius_km", 10), "distance_unit": "kilometer"}
                                                for x in geo["cities"] if x.get("key")]
    if aud.get("genders"):
        targeting["genders"] = aud["genders"]
    if aud.get("interests"):
        targeting["flexible_spec"] = [{"interests": [{"id": i["id"], "name": i.get("name")} for i in aud["interests"] if i.get("id")]}]
    if aud.get("custom_audience_ids"):
        targeting["custom_audiences"] = [{"id": x} for x in aud["custom_audience_ids"]]
    if not plc.get("automatic"):
        targeting["publisher_platforms"] = plc.get("publisher_platforms", [])
    promoted = {"page_id": cfg["page_id"]} if c.objective == "leads" else (
        {"pixel_id": cfg["pixel_id"], "custom_event_type": "PURCHASE"} if c.objective == "sales" else None)
    adset = client.create_ad_set(act, cid, f"{c.name} · ad set", c.objective, targeting, c.start_date, c.end_date, promoted)
    creative = client.create_creative(act, f"{c.name} · creative", cfg["page_id"], cfg.get("instagram_user_id"), cfg["copy"], image_hash)
    ad = client.create_ad(act, f"{c.name} · ad", adset, creative)
    for level, ext, parent in (("ad_set", adset, cid), ("creative", creative, adset), ("ad", ad, adset)):
        db.add(AdEntity(workspace_id=c.workspace_id, campaign_id=c.id, level=level, external_id=ext,
                        parent_external_id=parent, name=f"{c.name} · {level}", status="PAUSED"))
    _log(c, "structure_created", {"ad_set": adset, "creative": creative, "ad": ad})
    if activate:
        for obj in (ad, adset, cid):
            client.set_status(obj, "ACTIVE")
        _log(c, "activated")
    return cid


def _submit_google(db: Session, c: Campaign, acct: AdAccount, client: google.GoogleAdsClient, activate: bool) -> str:
    cfg = c.config
    cust = acct.external_id
    budget_rn = f"customers/{cust}/campaignBudgets/-1"
    campaign_rn = f"customers/{cust}/campaigns/-2"
    bidding = {"maximize_clicks": {"targetSpend": {}}, "maximize_conversions": {"maximizeConversions": {}},
               "manual_cpc": {"manualCpc": {}}}[cfg.get("bidding", "maximize_clicks")]
    ops: list[dict] = [
        {"campaignBudgetOperation": {"create": {"resourceName": budget_rn, "name": f"{c.name} budget {uuid.uuid4().hex[:6]}",
                                                "amountMicros": str((c.daily_budget_minor or 0) * 10_000),
                                                "deliveryMethod": "STANDARD", "explicitlyShared": False}}},
        {"campaignOperation": {"create": {
            "resourceName": campaign_rn, "name": c.name, "status": "PAUSED", "advertisingChannelType": "SEARCH",
            "campaignBudget": budget_rn, **bidding,
            "networkSettings": {"targetGoogleSearch": True, "targetSearchNetwork": bool(cfg.get("search_partners")),
                                "targetContentNetwork": False},
            **({"startDate": c.start_date.isoformat()} if c.start_date else {}),
            **({"endDate": c.end_date.isoformat()} if c.end_date else {}),
        }}},
    ]
    for loc in cfg.get("locations", []):
        ops.append({"campaignCriterionOperation": {"create": {"campaign": campaign_rn,
                                                              "location": {"geoTargetConstant": f"geoTargetConstants/{loc['id']}"}}}})
    for lang in cfg.get("language_ids", []):
        ops.append({"campaignCriterionOperation": {"create": {"campaign": campaign_rn,
                                                              "language": {"languageConstant": f"languageConstants/{lang}"}}}})
    for neg in cfg.get("negative_keywords", []):
        ops.append({"campaignCriterionOperation": {"create": {"campaign": campaign_rn, "negative": True,
                                                              "keyword": {"text": neg, "matchType": "BROAD"}}}})
    for i, g in enumerate(cfg.get("ad_groups", [])):
        group_rn = f"customers/{cust}/adGroups/-{10 + i}"
        ops.append({"adGroupOperation": {"create": {"resourceName": group_rn, "name": g["name"], "campaign": campaign_rn,
                                                    "status": "ENABLED", "type": "SEARCH_STANDARD"}}})
        for k in g["keywords"]:
            ops.append({"adGroupCriterionOperation": {"create": {"adGroup": group_rn, "status": "ENABLED",
                                                                 "keyword": {"text": k["text"], "matchType": k["match_type"]}}}})
        ops.append({"adGroupAdOperation": {"create": {"adGroup": group_rn, "status": "ENABLED", "ad": {
            "finalUrls": [g["final_url"]],
            "responsiveSearchAd": {"headlines": [{"text": h} for h in g["headlines"]],
                                   "descriptions": [{"text": d} for d in g["descriptions"]],
                                   **({"path1": g["paths"][0]} if g.get("paths") else {})}}}}})
    res = client.mutate(cust, ops)
    campaign_res = next(r["campaignResult"]["resourceName"] for r in res.get("mutateOperationResponses", []) if "campaignResult" in r)
    cid = campaign_res.split("/")[-1]
    _log(c, "structure_created", {"campaign": campaign_res, "operations": len(ops)})
    if activate:
        client.mutate(cust, [{"campaignOperation": {"update": {"resourceName": campaign_res, "status": "ENABLED"},
                                                    "updateMask": "status"}}])
        _log(c, "activated")
    return cid


@jobs.handler("ads.update")
def _job_update(db: Session, job: Job) -> dict:
    c = db.get(Campaign, uuid.UUID(job.payload["campaign_id"]))
    approval = db.get(Approval, uuid.UUID(job.payload["approval_id"])) if job.payload.get("approval_id") else None
    op = approval.payload if approval else job.payload["direct"]
    if approval is not None and approval.status != "approved":
        raise AppError("Update refused: approval not granted.")
    acct = db.get(AdAccount, c.ad_account_id)
    client = _client_for(db, acct)
    if op["operation"] == "set_status":
        if client is not None and c.external_id:
            if c.platform == "meta":
                client.set_status(c.external_id, op["status"])
            else:
                rn = f"customers/{acct.external_id}/campaigns/{c.external_id}"
                client.mutate(acct.external_id, [{"campaignOperation": {"update": {"resourceName": rn,
                              "status": "ENABLED" if op["status"] == "ACTIVE" else "PAUSED"}, "updateMask": "status"}}])
        c.status = "active" if op["status"] == "ACTIVE" else "paused"
        c.external_status = op["status"]
    else:
        changes = op["changes"]
        if client is not None and c.external_id:
            if c.platform == "meta":
                fields = {k: changes[k] for k in ("daily_budget_minor", "lifetime_budget_minor") if k in changes}
                if fields:
                    client.update_campaign(c.external_id, {"daily_budget": fields.get("daily_budget_minor"),
                                                           "lifetime_budget": fields.get("lifetime_budget_minor")})
                adsets = db.scalars(select(AdEntity).where(AdEntity.campaign_id == c.id, AdEntity.level == "ad_set")).all()
                if "end_date" in changes:
                    for s in adsets:
                        client.update_campaign(s.external_id, {"end_time": changes["end_date"]})
                if "config" in changes and any(k in changes["config"] for k in ("audience", "geo")):
                    cfg = changes["config"]
                    targeting = {"age_min": cfg["audience"]["age_min"], "age_max": cfg["audience"]["age_max"],
                                 "geo_locations": {"countries": cfg["geo"].get("countries", [])}}
                    for s in adsets:
                        client.update_campaign(s.external_id, {"targeting": targeting})
            elif "daily_budget_minor" in changes:
                rows = client.search(acct.external_id, f"SELECT campaign.campaign_budget FROM campaign WHERE campaign.id = {c.external_id}")
                budget_rn = rows[0]["campaign"]["campaignBudget"]
                client.mutate(acct.external_id, [{"campaignBudgetOperation": {"update": {
                    "resourceName": budget_rn, "amountMicros": str(changes["daily_budget_minor"] * 10_000)}, "updateMask": "amount_micros"}}])
        for k, v in changes.items():
            setattr(c, k, date.fromisoformat(v) if k in ("start_date", "end_date") and v else v)
    _log(c, "updated", {"operation": op})
    if approval is not None:
        approvals.mark_execution(db, approval.id, True, {"applied": op})
    audit.record(db, "campaign.updated_on_platform", workspace_id=c.workspace_id, actor_type="system", resource_type="campaign",
                 resource_id=c.id, data={"operation": op, "approval_id": str(approval.id) if approval else None})
    db.commit()
    return {"ok": True}


@jobs.on_failure("ads.update")
def _job_update_failed(db: Session, job: Job, message: str) -> None:
    c = db.get(Campaign, uuid.UUID(job.payload["campaign_id"]))
    if c is not None:
        c.last_error = message.split("\n")[0][:1000]
    approvals.mark_execution(db, job.payload.get("approval_id"), False, {"error": message.split("\n")[0][:500]})


@jobs.handler("ads.sync")
def _job_sync(db: Session, job: Job) -> dict:
    acct = db.get(AdAccount, uuid.UUID(job.payload["ad_account_id"]))
    conn = db.get(ConnectedAccount, acct.connected_account_id)
    if conn.mode == "sandbox":
        integrations.log_sync(db, conn, acct.workspace_id, conn.provider, "insights", True,
                              "Sandbox account: no performance data is generated.")
        db.commit()
        return {"rows": 0, "sandbox": True}
    client = _client_for(db, acct)
    until = date.today()
    since = until - timedelta(days=int(job.payload.get("days", 30)))
    by_ext = {c.external_id: c for c in db.scalars(select(Campaign).where(Campaign.ad_account_id == acct.id,
                                                                          Campaign.external_id.is_not(None)))}
    count = 0
    try:
        if acct.platform == "meta":
            for remote in client.campaigns(acct.external_id):
                _discover(db, acct, by_ext, remote["id"], remote["name"], remote.get("objective", ""),
                          remote.get("effective_status") or remote.get("status"), remote.get("daily_budget"))
            for row in client.insights(acct.external_id, since, until):
                c = by_ext.get(row.get("campaign_id"))
                if c is None:
                    continue
                _upsert_insight(db, c, date.fromisoformat(row["date_start"]), "meta", {
                    "impressions": int(row.get("impressions", 0)), "reach": int(row.get("reach", 0)),
                    "clicks": int(row.get("clicks", 0)), "spend_minor": round(float(row.get("spend", 0)) * 100),
                    "leads": int(meta.action_value(row.get("actions"), *meta.LEAD_ACTIONS)),
                    "purchases": int(meta.action_value(row.get("actions"), *meta.PURCHASE_ACTIONS)),
                    "revenue_minor": round(meta.action_value(row.get("action_values"), *meta.PURCHASE_ACTIONS) * 100),
                }, row)
                count += 1
        else:
            for row in client.campaigns(acct.external_id):
                camp = row.get("campaign", {})
                _discover(db, acct, by_ext, str(camp.get("id")), camp.get("name", ""), "traffic", camp.get("status"),
                          int(row.get("campaignBudget", {}).get("amountMicros", 0)) // 10_000 or None)
            for row in client.campaign_insights(acct.external_id, since, until):
                camp, m = row.get("campaign", {}), row.get("metrics", {})
                c = by_ext.get(str(camp.get("id")))
                if c is None:
                    continue
                conv = float(m.get("conversions", 0))
                _upsert_insight(db, c, date.fromisoformat(row["segments"]["date"]), "google", {
                    "impressions": int(m.get("impressions", 0)), "clicks": int(m.get("clicks", 0)),
                    "spend_minor": int(m.get("costMicros", 0)) // 10_000, "conversions": round(conv),
                    "revenue_minor": round(float(m.get("conversionsValue", 0)) * 100),
                    "search_impression_share": m.get("searchImpressionShare"),
                }, row)
                count += 1
        integrations.log_sync(db, conn, acct.workspace_id, conn.provider, "insights", True, records=count)
    except (meta.MetaError, google.GoogleError) as exc:
        db.rollback()
        integrations.log_sync(db, conn, acct.workspace_id, conn.provider, "insights", False, str(exc))
        db.commit()
        raise
    for c in by_ext.values():
        c.last_synced_at = utcnow()
    db.commit()
    return {"rows": count}


def _discover(db: Session, acct: AdAccount, by_ext: dict, ext: str, name: str, objective: str, status: str | None,
              daily_budget: int | str | None) -> None:
    """Campaign discovery: campaigns created outside MarketingOS appear read-only for reporting."""
    st = (status or "").upper()
    local_status = "active" if st in ("ACTIVE", "ENABLED") else "paused" if st in ("PAUSED",) else "archived"
    if ext in by_ext:
        c = by_ext[ext]
        c.external_status = st
        if c.status in LIVE or c.status == "archived":
            c.status = local_status
        return
    obj = next((k for k, v in meta.OBJECTIVES.items() if v == objective), "traffic")
    c = Campaign(workspace_id=acct.workspace_id, platform=acct.platform, ad_account_id=acct.id, name=name or ext,
                 objective=obj, status=local_status, external_status=st, external_id=ext, currency=acct.currency,
                 daily_budget_minor=int(daily_budget) if daily_budget else None, config={"discovered": True})
    db.add(c)
    db.flush()
    by_ext[ext] = c


def _upsert_insight(db: Session, c: Campaign, day: date, source: str, values: dict, raw: dict) -> None:
    row = db.scalar(select(AdInsight).where(AdInsight.campaign_id == c.id, AdInsight.entity_external_id == "",
                                            AdInsight.date == day))
    if row is None:
        row = AdInsight(workspace_id=c.workspace_id, campaign_id=c.id, platform=c.platform, date=day,
                        entity_level="campaign", entity_external_id="", entity_name=c.name, source=source)
        db.add(row)
    for k, v in values.items():
        setattr(row, k, v)
    row.raw = raw


@router.get("/ads/google/keywords")
def google_keywords(ctx: Ctx, db: DB, seed: str, location_id: str = "2356", language_id: str = "1000"):
    """Keyword ideas with volume, competition and bid ranges from Google's Keyword Planner."""
    ctx.require("ads:read")
    acct = db.scalar(select(AdAccount).where(AdAccount.workspace_id == ctx.workspace_id, AdAccount.platform == "google",
                                             AdAccount.status == "active"))
    seeds = [s.strip() for s in seed.split(",") if s.strip()]
    if acct is None:
        raise IntegrationRequired("Connect Google Ads to get keyword volumes and bid estimates.")
    client = _client_for(db, acct)
    if client is None:
        return {"source": "sandbox", "ideas": [{"text": k, "intent": kw_engine.intent(k), "avg_monthly_searches": None,
                                                "competition": None, "low_bid_minor": None, "high_bid_minor": None}
                                               for k in kw_engine.expand_seeds(seeds)],
                "note": "Sandbox account: keyword ideas only, no metrics."}
    ideas = client.keyword_ideas(acct.external_id, seeds, language_id, [location_id])
    out = []
    for i in ideas:
        m = i.get("keywordIdeaMetrics", {})
        out.append({"text": i.get("text"), "intent": kw_engine.intent(i.get("text", "")),
                    "avg_monthly_searches": int(m["avgMonthlySearches"]) if m.get("avgMonthlySearches") else None,
                    "competition": m.get("competition"),
                    "low_bid_minor": int(m["lowTopOfPageBidMicros"]) // 10_000 if m.get("lowTopOfPageBidMicros") else None,
                    "high_bid_minor": int(m["highTopOfPageBidMicros"]) // 10_000 if m.get("highTopOfPageBidMicros") else None})
    return {"source": "google_ads_keyword_planner", "ideas": out}


@router.get("/ads/google/conversion-tracking")
def conversion_tracking(ctx: Ctx, db: DB):
    """Conversion tracking diagnostics: is anything set up, and is it recording?"""
    ctx.require("ads:read")
    acct = db.scalar(select(AdAccount).where(AdAccount.workspace_id == ctx.workspace_id, AdAccount.platform == "google",
                                             AdAccount.status == "active"))
    if acct is None:
        raise IntegrationRequired("Connect Google Ads first.")
    client = _client_for(db, acct)
    if client is None:
        return {"source": "sandbox", "actions": [], "issues": ["Sandbox account: no conversion actions to inspect."]}
    actions = [r.get("conversionAction", {}) for r in client.conversion_actions(acct.external_id)]
    issues = []
    enabled = [a for a in actions if a.get("status") == "ENABLED"]
    if not enabled:
        issues.append("No enabled conversion actions: smart bidding and CPA reporting won't work.")
    since = date.today() - timedelta(days=30)
    conv = sum(r.conversions for r in db.scalars(select(AdInsight).where(AdInsight.workspace_id == ctx.workspace_id,
                                                                         AdInsight.platform == "google", AdInsight.date >= since)))
    clicks = sum(r.clicks for r in db.scalars(select(AdInsight).where(AdInsight.workspace_id == ctx.workspace_id,
                                                                      AdInsight.platform == "google", AdInsight.date >= since)))
    if enabled and clicks > 200 and conv == 0:
        issues.append(f"{clicks} clicks but no conversions in 30 days: check the tag fires on the thank-you page.")
    return {"source": "google_ads", "actions": actions, "clicks_30d": clicks, "conversions_30d": conv, "issues": issues}
