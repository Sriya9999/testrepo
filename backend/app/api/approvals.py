import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import DB, Ctx, WorkspaceContext, get_or_404
from app.errors import AppError
from app.models import Approval, Campaign, Client, ContentAsset, SocialPost, User
from app.services import approvals
from app.services.approvals import ACTIONS

router = APIRouter(tags=["approvals"])


class NoteIn(BaseModel):
    note: str | None = None


class BulkIn(BaseModel):
    ids: list[uuid.UUID]
    note: str | None = None


def _preview(db: Session, a: Approval) -> dict | None:
    if a.resource_type == "content":
        c = db.get(ContentAsset, a.resource_id)
        return {"type": "content", "title": c.title, "platform": c.platform, "format": c.format, "body": a.payload.get("body"),
                "quality": c.quality, "current_status": c.status} if c else None
    if a.resource_type == "social_post":
        p = db.get(SocialPost, a.resource_id)
        return {"type": "social_post", "caption": a.payload.get("caption"), "media": p.media if p else [],
                "format": a.payload.get("format"), "scheduled_at": a.payload.get("scheduled_at"),
                "current_status": p.status if p else None}
    if a.resource_type == "campaign":
        c = db.get(Campaign, a.resource_id)
        return {"type": "campaign", "campaign": a.payload.get("campaign") or {"campaign_id": str(a.resource_id)},
                "changes": a.payload.get("changes"), "operation": a.payload.get("operation"),
                "activate": a.payload.get("activate"), "current_status": c.status if c else None,
                "name": c.name if c else None}
    return None


def approval_out(db: Session, a: Approval, ctx=None, detail: bool = False) -> dict:
    spec = ACTIONS.get(a.action_type)
    requester = db.get(User, a.requested_by) if a.requested_by else None
    decider = db.get(User, a.decided_by) if a.decided_by else None
    client = db.scalar(select(Client).where(Client.client_workspace_id == a.workspace_id))
    out = {
        "id": str(a.id), "action_type": a.action_type, "action_label": spec.label if spec else a.action_type,
        "resource_type": a.resource_type, "resource_id": str(a.resource_id), "title": a.title, "platform": a.platform,
        "status": a.status, "budget_impact_minor": a.budget_impact_minor, "currency": a.currency,
        "ai_reasoning": a.ai_reasoning, "expected_outcome": a.expected_outcome,
        "requested_by": (requester.full_name or requester.email) if requester else None,
        "requested_by_agent": a.requested_by_agent, "decided_by": (decider.full_name or decider.email) if decider else None,
        "decided_at": a.decided_at, "decision_note": a.decision_note, "execution_result": a.execution_result,
        "executed_at": a.executed_at, "group_id": str(a.group_id) if a.group_id else None, "created_at": a.created_at,
        "client": client.name if client else None,
    }
    if ctx is not None:
        out["can_decide"] = a.status == "pending" and ctx.can("approvals:decide") and bool(spec) and ctx.can(spec.permission)
    if detail:
        out["preview"] = _preview(db, a)
        out["payload"] = a.payload
    return out


@router.get("/approvals")
def list_approvals(ctx: Ctx, db: DB, status: str = "pending", group_id: uuid.UUID | None = None, limit: int = 100):
    ctx.require("approvals:read")
    stmt = select(Approval).where(Approval.workspace_id == ctx.workspace_id)
    if status == "history":
        stmt = stmt.where(Approval.status != "pending")
    elif status != "all":
        stmt = stmt.where(Approval.status.in_(status.split(",")))
    if group_id:
        stmt = stmt.where(Approval.group_id == group_id)
    rows = db.scalars(stmt.order_by(Approval.created_at.desc()).limit(min(limit, 500)))
    return [approval_out(db, a, ctx, detail=True) for a in rows]


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: str, ctx: Ctx, db: DB):
    ctx.require("approvals:read")
    return approval_out(db, get_or_404(db, Approval, approval_id, ctx, "Approval"), ctx, detail=True)


def _decide(db: Session, ctx: WorkspaceContext, approval_id: str, decision: str, note: str | None) -> dict:
    a = get_or_404(db, Approval, approval_id, ctx, "Approval")
    approvals.decide(db, ctx, a, decision, note)
    db.commit()
    return approval_out(db, a, ctx, detail=True)


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, body: NoteIn, ctx: Ctx, db: DB):
    return _decide(db, ctx, approval_id, "approve", body.note)


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, body: NoteIn, ctx: Ctx, db: DB):
    return _decide(db, ctx, approval_id, "reject", body.note)


@router.post("/approvals/{approval_id}/request-changes")
def request_changes(approval_id: str, body: NoteIn, ctx: Ctx, db: DB):
    if not body.note:
        raise AppError("Say what should change.")
    return _decide(db, ctx, approval_id, "request_changes", body.note)


@router.post("/approvals/bulk-approve")
def bulk_approve(body: BulkIn, ctx: Ctx, db: DB):
    """Approve several items (e.g. everything an agent run proposed). Each is decided on its own."""
    results = []
    for aid in body.ids:
        try:
            out = _decide(db, ctx, str(aid), "approve", body.note)
            results.append({"id": str(aid), "ok": True, "status": out["status"]})
        except AppError as exc:
            db.rollback()
            results.append({"id": str(aid), "ok": False, "error": exc.message})
    return {"results": results}
