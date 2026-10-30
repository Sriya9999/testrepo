import uuid
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.db import utcnow
from app.deps import DB, Ctx, CurrentUser, WorkspaceContext, client_ip, get_or_404, load_workspace_context, require, resolve_role
from app.errors import AppError, Forbidden, NotFound
from app.models import (
    AuditLog,
    Brand,
    Client,
    ConnectedAccount,
    Invitation,
    Job,
    OrganizationMember,
    Subscription,
    User,
    Workspace,
    WorkspaceMember,
)
from app.permissions import ASSIGNABLE_ROLES, ROLE_LABELS, Role, role_rank
from app.services import accounts, audit, credits, jobs
from app.services.email import send_email
from app.services.policy import ACTION_POLICIES, workspace_settings

router = APIRouter(tags=["workspaces"])


def workspace_out(ws: Workspace, role: str | None = None, permissions=None) -> dict:
    out = {
        "id": str(ws.id), "name": ws.name, "kind": ws.kind, "timezone": ws.timezone, "currency": ws.currency,
        "industry": ws.industry, "organization_id": str(ws.organization_id), "status": ws.status,
        "settings": workspace_settings(ws), "created_at": ws.created_at,
    }
    if role:
        out["role"] = role
        out["role_label"] = ROLE_LABELS.get(role, role)
    if permissions is not None:
        out["permissions"] = sorted(permissions)
    return out


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = None


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    timezone: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    industry: str | None = None
    settings: dict | None = None


class MemberIn(BaseModel):
    email: EmailStr
    role: str


class MemberPatch(BaseModel):
    role: str


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, user: CurrentUser, db: DB):
    membership = db.scalar(select(OrganizationMember).where(
        OrganizationMember.user_id == user.id, OrganizationMember.role.in_(["owner", "admin"])))
    if membership is None:
        raise Forbidden("Only organization owners and administrators can create workspaces.")
    org_workspaces = db.scalars(select(Workspace).where(Workspace.organization_id == membership.organization_id)).all()
    accounts.check_limit(db, org_workspaces[0], "workspaces", len([w for w in org_workspaces if w.kind != "client"]))
    org = org_workspaces[0].organization
    ws = accounts.create_workspace(db, org, body.name, "business" if org.kind == "business" else "agency", body.industry)
    audit.record(db, "workspace.created", workspace_id=ws.id, organization_id=org.id, actor_id=user.id,
                 actor_label=user.email, resource_type="workspace", resource_id=ws.id)
    db.commit()
    return workspace_out(ws, resolve_role(db, user, ws))


@router.get("/workspaces")
def list_workspaces(user: CurrentUser, db: DB):
    return [workspace_out(ws, role) for ws, role in accounts.workspaces_for_user(db, user)]


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request, user: CurrentUser, db: DB):
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    out = workspace_out(ctx.workspace, ctx.role, ctx.permissions)
    out["action_policies"] = ACTION_POLICIES
    out["credit_balance"] = credits.get_wallet(db, ctx.workspace_id).balance
    plan = accounts.plan_for_workspace(db, ctx.workspace)
    out["plan"] = {"code": plan.code, "name": plan.name, "limits": plan.limits} if plan else None
    client = db.scalar(select(Client).where(Client.client_workspace_id == ctx.workspace_id))
    out["client_id"] = str(client.id) if client else None
    return out


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, body: WorkspacePatch, request: Request, user: CurrentUser, db: DB):
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    ctx.require("workspace:manage")
    ws = ctx.workspace
    changes = body.model_dump(exclude_none=True)
    for field in ("name", "timezone", "industry"):
        if field in changes:
            setattr(ws, field, changes[field])
    if "currency" in changes:
        ws.currency = changes["currency"].upper()
    if body.settings is not None:
        merged = dict(ws.settings or {})
        for section, values in body.settings.items():
            if section not in ("approvals", "spend_limits", "notifications", "agents") or not isinstance(values, dict):
                raise AppError(f"Unknown settings section '{section}'")
            merged[section] = {**merged.get(section, {}), **values}
        for key, value in merged.get("spend_limits", {}).items():
            if not isinstance(value, int) or value < 0:
                raise AppError(f"{key} must be a non-negative integer (minor currency units)")
        ws.settings = merged
    audit.record(db, "workspace.updated", ctx=ctx, resource_type="workspace", resource_id=ws.id, data=changes)
    db.commit()
    return workspace_out(ws, ctx.role, ctx.permissions)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str, request: Request, user: CurrentUser, db: DB):
    """Data deletion workflow: the workspace is locked immediately and purged after 7 days."""
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    ctx.require("workspace:delete")
    ctx.workspace.status = "pending_deletion"
    ctx.workspace.deletion_requested_at = utcnow()
    for account in db.scalars(select(ConnectedAccount).where(ConnectedAccount.workspace_id == ctx.workspace_id)):
        account.status = "disconnected"
    jobs.enqueue(db, "workspace.purge", {"workspace_id": ctx.workspace_id}, delay_seconds=7 * 24 * 3600)
    audit.record(db, "workspace.deletion_requested", ctx=ctx, resource_type="workspace", resource_id=ctx.workspace_id)
    db.commit()
    return {"status": "pending_deletion", "purge_after_days": 7}


@router.get("/workspaces/{workspace_id}/members")
def list_members(workspace_id: str, request: Request, user: CurrentUser, db: DB):
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    rows: dict[uuid.UUID, dict] = {}
    for m in db.scalars(select(OrganizationMember).where(
            OrganizationMember.organization_id == ctx.workspace.organization_id,
            OrganizationMember.role.in_(["owner", "admin"]))):
        role = Role.AGENCY_OWNER if m.role == "owner" else Role.ADMINISTRATOR
        rows[m.user_id] = {"role": role.value, "inherited": True}
    for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.workspace_id)):
        rows.setdefault(m.user_id, {"role": m.role, "inherited": False})
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(rows))))}
    members = [
        {"user_id": str(uid), "email": users[uid].email, "full_name": users[uid].full_name,
         "role": info["role"], "role_label": ROLE_LABELS.get(info["role"], info["role"]), "inherited": info["inherited"]}
        for uid, info in rows.items() if uid in users
    ]
    invites = [
        {"email": i.email, "role": i.role, "invited_at": i.created_at}
        for i in db.scalars(select(Invitation).where(Invitation.workspace_id == ctx.workspace_id, Invitation.accepted_at.is_(None)))
    ]
    return {"members": members, "invitations": invites,
            "assignable_roles": [{"value": r, "label": ROLE_LABELS[Role(r)]} for r in ASSIGNABLE_ROLES]}


def _check_assignable(ctx, role: str) -> None:
    if role not in ASSIGNABLE_ROLES:
        raise AppError(f"Unknown role '{role}'")
    if role_rank(role) < role_rank(ctx.role):
        raise Forbidden("You cannot grant a role with more access than your own.")


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def add_member(workspace_id: str, body: MemberIn, request: Request, user: CurrentUser, db: DB):
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    ctx.require("members:manage")
    _check_assignable(ctx, body.role)
    count = db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.workspace_id)) or 0
    accounts.check_limit(db, ctx.workspace, "members", count + 1)
    email = body.email.lower()
    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        db.add(Invitation(workspace_id=ctx.workspace_id, email=email, role=body.role, invited_by=user.id))
        send_email(email, f"You're invited to {ctx.workspace.name} on MarketingOS",
                   f"{user.full_name or user.email} invited you as {ROLE_LABELS[Role(body.role)]}. Create your account with this email to join.")
        status = "invited"
    else:
        existing = db.scalar(select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.user_id == target.id))
        if existing:
            existing.role = body.role
        else:
            db.add(WorkspaceMember(workspace_id=ctx.workspace_id, user_id=target.id, role=body.role))
        status = "added"
    audit.record(db, "member.added", ctx=ctx, resource_type="user", resource_id=target.id if target else None,
                 data={"email": email, "role": body.role, "status": status})
    db.commit()
    return {"status": status, "email": email, "role": body.role}


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
def update_member(workspace_id: str, user_id: uuid.UUID, body: MemberPatch, request: Request, user: CurrentUser, db: DB):
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    ctx.require("members:manage")
    _check_assignable(ctx, body.role)
    member = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.user_id == user_id))
    if member is None:
        raise NotFound("Member not found (organization owners and admins are managed at organization level)")
    if role_rank(member.role) < role_rank(ctx.role):
        raise Forbidden("You cannot change the role of someone with more access than you.")
    old = member.role
    member.role = body.role
    audit.record(db, "member.role_changed", ctx=ctx, resource_type="user", resource_id=user_id, data={"from": old, "to": body.role})
    db.commit()
    return {"user_id": str(user_id), "role": body.role}


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: uuid.UUID, request: Request, user: CurrentUser, db: DB):
    ctx = load_workspace_context(db, user, workspace_id, client_ip(request))
    ctx.require("members:manage")
    member = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.user_id == user_id))
    if member is None:
        raise NotFound("Member not found")
    if role_rank(member.role) < role_rank(ctx.role):
        raise Forbidden("You cannot remove someone with more access than you.")
    db.delete(member)
    audit.record(db, "member.removed", ctx=ctx, resource_type="user", resource_id=user_id)
    db.commit()


@router.get("/audit-logs")
def audit_logs(db: DB, ctx: WorkspaceContext = require("audit:read"), action: str | None = None, limit: int = 100):
    stmt = select(AuditLog).where(AuditLog.workspace_id == ctx.workspace_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(min(limit, 500))).all()
    return [
        {"id": str(r.id), "action": r.action, "actor_type": r.actor_type, "actor": r.actor_label,
         "resource_type": r.resource_type, "resource_id": r.resource_id, "data": r.data, "ip": r.ip,
         "created_at": r.created_at}
        for r in rows
    ]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, ctx: Ctx, db: DB):
    job = get_or_404(db, Job, job_id, ctx, "Job")
    return jobs.job_status(job)


# ---- agency clients -------------------------------------------------------------------

class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    account_manager_id: uuid.UUID | None = None
    notes: str = ""


class ClientPatch(BaseModel):
    name: str | None = None
    industry: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    account_manager_id: uuid.UUID | None = None
    status: Literal["active", "paused", "archived"] | None = None
    notes: str | None = None


class AllocateIn(BaseModel):
    amount: int = Field(gt=0)
    direction: Literal["to_client", "to_agency"] = "to_client"


def _agency(ctx) -> None:
    if ctx.workspace.kind != "agency":
        raise AppError("Switch to your agency workspace to manage clients.", code="not_agency_workspace")


def client_out(db, client: Client, user: User) -> dict:
    ws = db.get(Workspace, client.client_workspace_id)
    platforms = sorted({a.provider for a in db.scalars(select(ConnectedAccount).where(
        ConnectedAccount.workspace_id == client.client_workspace_id, ConnectedAccount.status == "connected"))})
    sub = db.scalar(select(Subscription).where(Subscription.organization_id == ws.organization_id))
    manager = db.get(User, client.account_manager_id) if client.account_manager_id else None
    last = db.scalar(select(func.max(AuditLog.created_at)).where(AuditLog.workspace_id == client.client_workspace_id))
    return {
        "id": str(client.id), "name": client.name, "industry": client.industry, "status": client.status,
        "workspace_id": str(client.client_workspace_id), "contact_name": client.contact_name,
        "contact_email": client.contact_email, "notes": client.notes,
        "account_manager": {"id": str(manager.id), "name": manager.full_name or manager.email} if manager else None,
        "connected_platforms": platforms,
        "subscription_status": sub.status if sub else None,
        "credit_balance": credits.get_wallet(db, client.client_workspace_id).balance,
        "last_activity_at": max([d for d in (last, client.last_activity_at) if d is not None], default=None),
        "created_at": client.created_at,
    }


def _visible_clients(db, ctx) -> list[Client]:
    rows = db.scalars(select(Client).where(Client.agency_workspace_id == ctx.workspace_id).order_by(Client.name)).all()
    if ctx.role in (Role.AGENCY_OWNER, Role.ADMINISTRATOR):
        return list(rows)
    assigned = {m.workspace_id for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == ctx.user.id))}
    return [c for c in rows if c.client_workspace_id in assigned]


@router.get("/agency/clients")
def list_clients(ctx: Ctx, db: DB):
    _agency(ctx)
    return [client_out(db, c, ctx.user) for c in _visible_clients(db, ctx)]


@router.post("/agency/clients", status_code=201)
def create_client(body: ClientIn, db: DB, ctx: WorkspaceContext = require("clients:manage")):
    _agency(ctx)
    accounts.check_limit(db, ctx.workspace, "client_workspaces", accounts.count_clients(db, ctx.workspace_id))
    org = ctx.workspace.organization
    ws = accounts.create_workspace(db, org, body.name, "client", body.industry)
    client = Client(
        agency_workspace_id=ctx.workspace_id, client_workspace_id=ws.id, name=body.name, industry=body.industry,
        contact_name=body.contact_name, contact_email=body.contact_email, notes=body.notes,
        account_manager_id=body.account_manager_id,
    )
    db.add(client)
    db.add(Brand(workspace_id=ws.id, name=body.name, industry=body.industry, is_default=True))
    if body.account_manager_id:
        _assign_manager(db, ws.id, body.account_manager_id, ctx)
    elif ctx.role not in (Role.AGENCY_OWNER, Role.ADMINISTRATOR):
        # Account managers who create a client manage it.
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=ctx.user.id, role=Role.ACCOUNT_MANAGER.value))
        client.account_manager_id = ctx.user.id
    audit.record(db, "client.created", ctx=ctx, resource_type="client", resource_id=client.id, data={"name": body.name})
    db.commit()
    return client_out(db, client, ctx.user)


def _assign_manager(db, workspace_id: uuid.UUID, user_id: uuid.UUID, ctx) -> None:
    manager = db.get(User, user_id)
    if manager is None:
        raise NotFound("Account manager not found")
    in_agency = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.user_id == user_id)) or db.scalar(
        select(OrganizationMember).where(OrganizationMember.organization_id == ctx.workspace.organization_id,
                                         OrganizationMember.user_id == user_id))
    if not in_agency:
        raise AppError("The account manager must be a member of the agency workspace.")
    existing = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))
    if existing is None:
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=Role.ACCOUNT_MANAGER.value))


def _get_client(db, ctx, client_id) -> Client:
    _agency(ctx)
    for c in _visible_clients(db, ctx):
        if str(c.id) == str(client_id):
            return c
    raise NotFound("Client not found")


@router.get("/agency/clients/{client_id}")
def get_client(client_id: str, ctx: Ctx, db: DB):
    return client_out(db, _get_client(db, ctx, client_id), ctx.user)


@router.patch("/agency/clients/{client_id}")
def update_client(client_id: str, body: ClientPatch, db: DB, ctx: WorkspaceContext = require("clients:manage")):
    client = _get_client(db, ctx, client_id)
    changes = body.model_dump(exclude_unset=True)
    if "account_manager_id" in changes and changes["account_manager_id"]:
        _assign_manager(db, client.client_workspace_id, changes["account_manager_id"], ctx)
    for key, value in changes.items():
        setattr(client, key, value)
    if "name" in changes:
        db.get(Workspace, client.client_workspace_id).name = changes["name"]
    audit.record(db, "client.updated", ctx=ctx, resource_type="client", resource_id=client.id,
                 data={k: str(v) for k, v in changes.items()})
    db.commit()
    return client_out(db, client, ctx.user)


@router.post("/agency/clients/{client_id}/credits")
def allocate_credits(client_id: str, body: AllocateIn, db: DB, ctx: WorkspaceContext = require("credits:allocate")):
    client = _get_client(db, ctx, client_id)
    src, dst = (ctx.workspace_id, client.client_workspace_id)
    if body.direction == "to_agency":
        src, dst = dst, src
    credits.allocate(db, src, dst, body.amount, ctx.user.id)
    audit.record(db, "credits.allocated", ctx=ctx, resource_type="client", resource_id=client.id,
                 data={"amount": body.amount, "direction": body.direction})
    db.commit()
    return {"agency_balance": credits.get_wallet(db, ctx.workspace_id).balance,
            "client_balance": credits.get_wallet(db, client.client_workspace_id).balance}

