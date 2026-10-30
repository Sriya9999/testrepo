"""Central approval engine.

Anything that publishes, spends money or changes a live campaign is proposed as an Approval
holding the exact payload that will execute. On approval the engine re-reads the resource,
and refuses to execute if it changed after the request was made (payload hash mismatch), so
what runs is always what a human approved.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.errors import AppError, Conflict, Forbidden
from app.models import Approval, User
from app.services import audit
from app.services.notifications import notify_workspace
from app.services.policy import workspace_settings


@dataclass
class ActionSpec:
    permission: str
    execute: Callable[[Session, Approval, User], dict]
    snapshot: Callable[[Session, Approval], dict] | None = None
    on_rejected: Callable[[Session, Approval], None] | None = None
    label: str = ""


ACTIONS: dict[str, ActionSpec] = {}


def register_action(action_type: str, spec: ActionSpec) -> None:
    ACTIONS[action_type] = spec


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def request_approval(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    action_type: str,
    resource_type: str,
    resource_id: uuid.UUID,
    title: str,
    payload: dict,
    platform: str | None = None,
    budget_impact_minor: int | None = None,
    currency: str | None = None,
    ai_reasoning: str | None = None,
    expected_outcome: str | None = None,
    requested_by: uuid.UUID | None = None,
    requested_by_agent: str | None = None,
    group_id: uuid.UUID | None = None,
) -> Approval:
    if action_type not in ACTIONS:
        raise AppError(f"Unknown approval action '{action_type}'")
    # A new request replaces any still-pending request for the same thing.
    for old in db.scalars(
        select(Approval).where(
            Approval.workspace_id == workspace_id,
            Approval.resource_id == resource_id,
            Approval.action_type == action_type,
            Approval.status == "pending",
        )
    ):
        old.status = "superseded"
    approval = Approval(
        workspace_id=workspace_id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        title=title,
        platform=platform,
        payload=payload,
        payload_hash=payload_hash(payload),
        budget_impact_minor=budget_impact_minor,
        currency=currency,
        ai_reasoning=ai_reasoning,
        expected_outcome=expected_outcome,
        requested_by=requested_by,
        requested_by_agent=requested_by_agent,
        group_id=group_id,
    )
    db.add(approval)
    db.flush()
    audit.record(
        db, "approval.requested", workspace_id=workspace_id,
        actor_type="agent" if requested_by_agent else "user", actor_id=requested_by,
        actor_label=requested_by_agent, resource_type="approval", resource_id=approval.id,
        data={"action_type": action_type, "resource_type": resource_type, "resource_id": str(resource_id)},
    )
    notify_workspace(
        db, workspace_id, ACTIONS[action_type].permission, "approval_requested",
        f"Approval needed: {title}", ai_reasoning or "", {"approval_id": str(approval.id)},
        exclude_user=requested_by,
    )
    return approval


def decide(db: Session, ctx, approval: Approval, decision: str, note: str | None = None) -> Approval:
    if approval.status != "pending":
        raise Conflict(f"This approval is already {approval.status}.")
    spec = ACTIONS[approval.action_type]
    ctx.require("approvals:decide")
    ctx.require(spec.permission)
    if decision == "approve" and approval.requested_by == ctx.user.id:
        if not workspace_settings(ctx.workspace)["approvals"]["allow_self_approval"]:
            raise Forbidden("This workspace requires someone else to approve your requests.")

    approval.decided_by = ctx.user.id
    approval.decided_at = utcnow()
    approval.decision_note = note

    if decision == "approve":
        if spec.snapshot is not None:
            current = spec.snapshot(db, approval)
            if payload_hash(current) != approval.payload_hash:
                approval.status = "superseded"
                audit.record(db, "approval.stale", ctx=ctx, resource_type="approval", resource_id=approval.id)
                db.commit()
                raise Conflict(
                    "The item changed after this approval was requested. Review the latest version and request approval again.",
                    code="approval_stale",
                )
        approval.status = "approved"
        result = spec.execute(db, approval, ctx.user) or {}
        approval.execution_result = result
        if result.get("executed"):
            approval.status = "executed"
            approval.executed_at = utcnow()
    elif decision in ("reject", "request_changes"):
        approval.status = "rejected" if decision == "reject" else "changes_requested"
        if spec.on_rejected is not None:
            spec.on_rejected(db, approval)
    else:
        raise AppError("decision must be approve, reject or request_changes")

    audit.record(
        db, f"approval.{approval.status}", ctx=ctx, resource_type="approval", resource_id=approval.id,
        data={"action_type": approval.action_type, "note": note, "resource_id": str(approval.resource_id)},
    )
    if approval.requested_by and approval.requested_by != ctx.user.id:
        from app.services.notifications import notify_user

        notify_user(
            db, approval.requested_by, approval.workspace_id, "approval_decided",
            f"{approval.title}: {approval.status.replace('_', ' ')}", note or "", {"approval_id": str(approval.id)},
        )
    return approval


def mark_execution(db: Session, approval_id: uuid.UUID | str | None, ok: bool, result: dict) -> None:
    """Called by background jobs once an approved action has actually run."""
    if not approval_id:
        return
    approval = db.get(Approval, uuid.UUID(str(approval_id)))
    if approval is None:
        return
    approval.status = "executed" if ok else "failed"
    approval.execution_result = {**(approval.execution_result or {}), **result}
    approval.executed_at = utcnow()
