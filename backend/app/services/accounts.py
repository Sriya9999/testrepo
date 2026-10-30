import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_aware, utcnow
from app.errors import AppError, Conflict, Unauthorized
from app.models import (
    Brand,
    Client,
    Invitation,
    OneTimeToken,
    Organization,
    OrganizationMember,
    Plan,
    RefreshToken,
    Subscription,
    User,
    Workspace,
    WorkspaceMember,
)
from app.security import create_access_token, hash_token, random_token
from app.services import audit, credits
from app.services.email import send_email

TRIAL_DAYS = 14
TRIAL_CREDITS = 100


def create_workspace(db: Session, org: Organization, name: str, kind: str, industry: str | None = None) -> Workspace:
    ws = Workspace(organization_id=org.id, name=name, kind=kind, industry=industry)
    db.add(ws)
    db.flush()
    credits.get_wallet(db, ws.id)
    return ws


def create_account(
    db: Session, *, email: str, full_name: str, account_type: str, organization_name: str,
    password_hash: str | None = None, google_sub: str | None = None, verified: bool = False,
) -> tuple[User, Workspace]:
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("An account with this email already exists.")
    if account_type not in ("business", "agency"):
        raise AppError("account_type must be business or agency")
    user = User(
        email=email, full_name=full_name.strip(), password_hash=password_hash, google_sub=google_sub,
        email_verified_at=utcnow() if verified else None,
    )
    db.add(user)
    db.flush()
    org = Organization(name=organization_name.strip() or full_name, kind=account_type, owner_id=user.id)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    ws = create_workspace(db, org, org.name, "agency" if account_type == "agency" else "business")

    plan = db.scalar(select(Plan).where(Plan.code == ("agency" if account_type == "agency" else "starter")))
    if plan is not None:
        now = utcnow()
        db.add(Subscription(
            organization_id=org.id, plan_id=plan.id, status="trialing",
            current_period_start=now, current_period_end=now + timedelta(days=TRIAL_DAYS),
        ))
    credits.grant(db, ws.id, TRIAL_CREDITS, description=f"{TRIAL_DAYS}-day trial credits")
    apply_invitations(db, user)
    audit.record(db, "account.registered", workspace_id=ws.id, organization_id=org.id, actor_id=user.id,
                 actor_label=email, resource_type="user", resource_id=user.id)
    return user, ws


def apply_invitations(db: Session, user: User) -> None:
    for inv in db.scalars(select(Invitation).where(Invitation.email == user.email, Invitation.accepted_at.is_(None))):
        exists = db.scalar(select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == inv.workspace_id, WorkspaceMember.user_id == user.id))
        if not exists:
            db.add(WorkspaceMember(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role))
        inv.accepted_at = utcnow()


def issue_tokens(db: Session, user: User, user_agent: str | None = None, ip: str | None = None) -> dict:
    raw = random_token()
    db.add(RefreshToken(
        user_id=user.id, token_hash=hash_token(raw),
        expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days),
        user_agent=(user_agent or "")[:300], ip=ip,
    ))
    user.last_login_at = utcnow()
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": raw,
        "token_type": "bearer",
        "expires_in": get_settings().access_token_minutes * 60,
    }


def rotate_refresh_token(db: Session, raw: str, user_agent: str | None, ip: str | None) -> tuple[User, dict]:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if token is None or as_aware(token.expires_at) < utcnow():
        raise Unauthorized("Session expired. Please sign in again.")
    if token.revoked_at is not None:
        # A revoked token being reused means it leaked: end every session for this user.
        for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == token.user_id, RefreshToken.revoked_at.is_(None))):
            t.revoked_at = utcnow()
        db.commit()
        raise Unauthorized("Session expired. Please sign in again.")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is not active")
    token.revoked_at = utcnow()
    return user, issue_tokens(db, user, user_agent, ip)


def create_one_time_token(db: Session, user: User, purpose: str, ttl: timedelta) -> str:
    raw = random_token()
    db.add(OneTimeToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw), expires_at=utcnow() + ttl))
    return raw


def consume_one_time_token(db: Session, raw: str, purpose: str) -> User:
    token = db.scalar(select(OneTimeToken).where(OneTimeToken.token_hash == hash_token(raw), OneTimeToken.purpose == purpose))
    if token is None or token.used_at is not None or as_aware(token.expires_at) < utcnow():
        raise AppError("This link is invalid or has expired.", code="invalid_token")
    token.used_at = utcnow()
    user = db.get(User, token.user_id)
    if user is None:
        raise AppError("This link is invalid or has expired.", code="invalid_token")
    return user


def send_verification(db: Session, user: User) -> None:
    raw = create_one_time_token(db, user, "verify_email", timedelta(hours=get_settings().email_token_hours))
    link = f"{get_settings().web_origin}/verify-email?token={raw}"
    send_email(user.email, "Verify your MarketingOS email", f"Hi {user.full_name or ''},\n\nConfirm your email: {link}\n")


def workspaces_for_user(db: Session, user: User) -> list[tuple[Workspace, str]]:
    from app.deps import resolve_role

    org_ids = [m.organization_id for m in db.scalars(select(OrganizationMember).where(
        OrganizationMember.user_id == user.id, OrganizationMember.role.in_(["owner", "admin"])))]
    ws_ids = [m.workspace_id for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))]
    rows = db.scalars(
        select(Workspace).where((Workspace.organization_id.in_(org_ids)) | (Workspace.id.in_(ws_ids)))
        .order_by(Workspace.kind, Workspace.name)
    ).all()
    result = []
    for ws in rows:
        role = resolve_role(db, user, ws)
        if role:
            result.append((ws, role))
    return result


def plan_for_workspace(db: Session, workspace: Workspace) -> Plan | None:
    sub = db.scalar(select(Subscription).where(Subscription.organization_id == workspace.organization_id))
    return db.get(Plan, sub.plan_id) if sub else None


def check_limit(db: Session, workspace: Workspace, key: str, current: int) -> None:
    plan = plan_for_workspace(db, workspace)
    if plan is None:
        return
    limit = (plan.limits or {}).get(key)
    if limit is not None and current >= limit:
        raise AppError(
            f"Your {plan.name} plan allows {limit} {key.replace('_', ' ')}. Upgrade to add more.",
            code="plan_limit", details={"limit": limit, "key": key, "plan": plan.code},
        )


def count_clients(db: Session, agency_workspace_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Client).where(Client.agency_workspace_id == agency_workspace_id)) or 0


def default_brand(db: Session, workspace_id: uuid.UUID) -> Brand | None:
    return db.scalar(
        select(Brand).where(Brand.workspace_id == workspace_id).order_by(Brand.is_default.desc(), Brand.created_at)
    )
