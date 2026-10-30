import uuid
from dataclasses import dataclass, field
from typing import Annotated

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import Forbidden, NotFound, Unauthorized
from app.models import OrganizationMember, User, Workspace, WorkspaceMember
from app.permissions import Role, permissions_for
from app.security import decode_token

DB = Annotated[Session, Depends(get_db)]


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token")
    return token


def user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_token(token, "access")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthorized("Invalid or expired token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is not active")
    return user


def get_current_user(request: Request, db: DB) -> User:
    return user_from_token(db, _bearer(request))


CurrentUser = Annotated[User, Depends(get_current_user)]


def resolve_role(db: Session, user: User, workspace: Workspace) -> str | None:
    """Organization owners/admins see every workspace in their organization; everyone else
    needs an explicit workspace membership (agencies assign staff to specific clients)."""
    org_member = db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == workspace.organization_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if org_member and org_member.role == "owner":
        return Role.AGENCY_OWNER.value
    if org_member and org_member.role == "admin":
        return Role.ADMINISTRATOR.value
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id
        )
    )
    return member.role if member else None


@dataclass
class WorkspaceContext:
    user: User
    workspace: Workspace
    role: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    ip: str | None = None

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise Forbidden(f"Your role ({self.role}) does not allow '{permission}'.")


def load_workspace_context(db: Session, user: User, workspace_id: str | uuid.UUID, ip: str | None = None) -> WorkspaceContext:
    try:
        ws_uuid = uuid.UUID(str(workspace_id))
    except ValueError as exc:
        raise NotFound("Workspace not found") from exc
    workspace = db.get(Workspace, ws_uuid)
    if workspace is None:
        raise NotFound("Workspace not found")
    role = resolve_role(db, user, workspace)
    if role is None:
        # Same response as a missing workspace, so tenants cannot probe each other's ids.
        raise NotFound("Workspace not found")
    if workspace.status == "pending_deletion":
        raise Forbidden("This workspace is scheduled for deletion.")
    return WorkspaceContext(user=user, workspace=workspace, role=role, permissions=permissions_for(role), ip=ip)


def get_workspace_context(
    request: Request,
    db: DB,
    user: CurrentUser,
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> WorkspaceContext:
    if not x_workspace_id:
        raise NotFound("Select a workspace (X-Workspace-Id header)")
    return load_workspace_context(db, user, x_workspace_id, client_ip(request))


Ctx = Annotated[WorkspaceContext, Depends(get_workspace_context)]


def require(*permissions: str):
    def checker(ctx: Ctx) -> WorkspaceContext:
        for permission in permissions:
            ctx.require(permission)
        return ctx

    return Depends(checker)


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_or_404(db: Session, model, obj_id, ctx: WorkspaceContext, label: str | None = None):
    """Fetch a tenant-scoped row, refusing rows that belong to another workspace."""
    try:
        obj = db.get(model, uuid.UUID(str(obj_id)))
    except ValueError:
        obj = None
    if obj is None or getattr(obj, "workspace_id", None) != ctx.workspace_id:
        raise NotFound(f"{label or model.__name__} not found")
    return obj
