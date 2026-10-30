from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app.api.analytics import scope
from app.api.approvals import approval_out
from app.deps import DB, Ctx
from app.engines import ads_optimizer, analytics
from app.models import AdInsight, Approval, Campaign, ConnectedAccount, SocialPost
from app.services import credits

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(ctx: Ctx, db: DB, start: date | None = None, end: date | None = None, client_ids: str | None = None,
              platform: str | None = None, all_clients: bool = False):
    """Everything the main dashboard shows, in one call."""
    ctx.require("analytics:read")
    import uuid

    end = end or date.today()
    start = start or end - timedelta(days=29)
    ids = scope(db, ctx, [uuid.UUID(c) for c in client_ids.split(",")] if client_ids else None, all_clients)
    ov = analytics.overview(db, ids, start, end, ctx.workspace.currency)
    series = analytics.series(db, ids, start, end)
    if platform in ("meta", "google"):
        series["paid"] = {platform: series["paid"].get(platform, [])}
    pending = db.scalars(select(Approval).where(Approval.workspace_id.in_(ids), Approval.status == "pending")
                         .order_by(Approval.created_at.desc()).limit(5)).all()
    stmt = select(Campaign).where(Campaign.workspace_id.in_(ids))
    if platform in ("meta", "google"):
        stmt = stmt.where(Campaign.platform == platform)
    campaigns = db.scalars(stmt.order_by(Campaign.updated_at.desc()).limit(6)).all()
    rows = db.scalars(select(AdInsight).where(AdInsight.workspace_id.in_(ids), AdInsight.entity_level == "campaign",
                                              AdInsight.date >= start, AdInsight.date <= end)).all()
    camp_map = {c.id: c for c in db.scalars(select(Campaign).where(Campaign.workspace_id.in_(ids)))}
    accounts = db.scalars(select(ConnectedAccount).where(ConnectedAccount.workspace_id.in_(ids),
                                                         ConnectedAccount.status != "disconnected")).all()
    upcoming = db.scalars(select(SocialPost).where(SocialPost.workspace_id.in_(ids), SocialPost.status.in_(["scheduled", "in_review"]))
                          .order_by(SocialPost.scheduled_at).limit(5)).all()
    by_campaign: dict = {}
    for r in rows:
        by_campaign.setdefault(r.campaign_id, []).append(r)
    return {
        **ov,
        "summary": analytics.summary_text(ov, ctx.workspace.currency),
        "series": series,
        "pending_approvals": [approval_out(db, a, ctx) for a in pending],
        "pending_approvals_count": db.query(Approval).filter(Approval.workspace_id.in_(ids), Approval.status == "pending").count(),
        "recent_campaigns": [{"id": str(c.id), "name": c.name, "platform": c.platform, "status": c.status,
                              "metrics": ads_optimizer.totals(by_campaign[c.id]) if c.id in by_campaign else None} for c in campaigns],
        "recommendations": ads_optimizer.analyze(rows, camp_map, ctx.workspace.currency)[:5],
        "upcoming_posts": [{"id": str(p.id), "caption": p.caption[:100], "scheduled_at": p.scheduled_at, "status": p.status} for p in upcoming],
        "data_freshness": [{"provider": a.provider, "name": a.display_name, "mode": a.mode, "status": a.status,
                            "last_sync_at": a.last_sync_at, "error": a.last_error} for a in accounts],
        "credits": {"balance": credits.get_wallet(db, ctx.workspace_id).balance},
    }
