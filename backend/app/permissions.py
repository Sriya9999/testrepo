"""Roles and permissions. Checked server-side on every request (see app.deps)."""

from enum import StrEnum


class Role(StrEnum):
    AGENCY_OWNER = "agency_owner"
    ADMINISTRATOR = "administrator"
    ACCOUNT_MANAGER = "account_manager"
    MARKETING_MANAGER = "marketing_manager"
    CONTENT_CREATOR = "content_creator"
    ANALYST = "analyst"
    CLIENT_APPROVER = "client_approver"
    VIEWER = "viewer"


ROLE_LABELS = {
    Role.AGENCY_OWNER: "Agency Owner",
    Role.ADMINISTRATOR: "Administrator",
    Role.ACCOUNT_MANAGER: "Account Manager",
    Role.MARKETING_MANAGER: "Marketing Manager",
    Role.CONTENT_CREATOR: "Content Creator",
    Role.ANALYST: "Analyst",
    Role.CLIENT_APPROVER: "Client Approver",
    Role.VIEWER: "Viewer",
}

READ = {
    "workspace:read", "brand:read", "content:read", "social:read", "ads:read", "seo:read",
    "geo:read", "analytics:read", "approvals:read", "agents:read",
}
CREATE_CONTENT = {"brand:write", "content:write", "social:write", "media:upload"}
MANAGE_MARKETING = CREATE_CONTENT | {
    "ads:write", "seo:write", "geo:write", "analytics:export", "agents:run", "content:approve",
    "approvals:decide", "social:schedule", "ads:approve", "integrations:read", "billing:read",
}
ADMIN = MANAGE_MARKETING | {
    "workspace:manage", "members:manage", "integrations:manage", "billing:manage",
    "clients:manage", "audit:read", "credits:allocate",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.AGENCY_OWNER: frozenset(READ | ADMIN | {"workspace:delete"}),
    Role.ADMINISTRATOR: frozenset(READ | ADMIN),
    Role.ACCOUNT_MANAGER: frozenset(READ | MANAGE_MARKETING | {"clients:manage", "integrations:manage"}),
    Role.MARKETING_MANAGER: frozenset(READ | MANAGE_MARKETING),
    Role.CONTENT_CREATOR: frozenset(READ | CREATE_CONTENT | {"agents:run"}),
    Role.ANALYST: frozenset(READ | {"analytics:export"}),
    Role.CLIENT_APPROVER: frozenset(READ | {"content:approve", "approvals:decide", "ads:approve"}),
    Role.VIEWER: frozenset(READ),
}

ASSIGNABLE_ROLES = [r.value for r in Role if r != Role.AGENCY_OWNER]


def permissions_for(role: str | None) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role or "", frozenset())


def role_rank(role: str) -> int:
    """Lower is more privileged; used to stop users granting roles above their own."""
    order = [r.value for r in Role]
    return order.index(role) if role in order else len(order)
