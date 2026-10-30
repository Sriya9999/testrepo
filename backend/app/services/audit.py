import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    ctx=None,
    workspace_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    actor_type: str = "user",
    actor_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    resource_type: str | None = None,
    resource_id: Any = None,
    data: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append an audit entry. Pass `ctx` (WorkspaceContext) to fill actor/workspace/ip."""
    if ctx is not None:
        workspace_id = workspace_id or ctx.workspace_id
        organization_id = organization_id or ctx.workspace.organization_id
        actor_id = actor_id or ctx.user.id
        actor_label = actor_label or ctx.user.email
        ip = ip or ctx.ip
    entry = AuditLog(
        workspace_id=workspace_id,
        organization_id=organization_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        data=data or {},
        ip=ip,
    )
    db.add(entry)
    return entry
