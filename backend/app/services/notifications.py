import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, OrganizationMember, Workspace, WorkspaceMember
from app.permissions import Role, permissions_for


def users_with_permission(db: Session, workspace_id: uuid.UUID, permission: str) -> set[uuid.UUID]:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return set()
    users: set[uuid.UUID] = set()
    for m in db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == workspace.organization_id)):
        role = {"owner": Role.AGENCY_OWNER, "admin": Role.ADMINISTRATOR}.get(m.role)
        if role and permission in permissions_for(role):
            users.add(m.user_id)
    for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)):
        if permission in permissions_for(m.role):
            users.add(m.user_id)
    return users


def notify_user(
    db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID | None, kind: str, title: str, body: str = "",
    data: dict | None = None,
) -> Notification:
    n = Notification(user_id=user_id, workspace_id=workspace_id, kind=kind, title=title[:300], body=body, data=data or {})
    db.add(n)
    return n


def notify_workspace(
    db: Session, workspace_id: uuid.UUID, permission: str, kind: str, title: str, body: str = "",
    data: dict | None = None, exclude_user: uuid.UUID | None = None,
) -> int:
    count = 0
    for user_id in users_with_permission(db, workspace_id, permission):
        if user_id == exclude_user:
            continue
        notify_user(db, user_id, workspace_id, kind, title, body, data)
        count += 1
    return count
