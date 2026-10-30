import uuid
from datetime import timedelta
from typing import Literal

import jwt
import pyotp
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.deps import DB, CurrentUser, client_ip
from app.errors import AppError, Forbidden, ServiceUnavailable, Unauthorized
from app.models import Notification, Organization, PushDevice, RefreshToken, User
from app.security import (
    create_mfa_challenge,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from app.services import accounts, audit
from app.services.email import send_email
from app.services.ratelimit import limit_auth

router = APIRouter(tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    account_type: Literal["business", "agency"] = "business"
    organization_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MfaLoginIn(BaseModel):
    mfa_token: str
    code: str


class RefreshIn(BaseModel):
    refresh_token: str


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class GoogleIn(BaseModel):
    id_token: str
    account_type: Literal["business", "agency"] = "business"
    organization_name: str | None = None


def user_out(db, user: User) -> dict:
    workspaces = accounts.workspaces_for_user(db, user)
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "email_verified": user.email_verified_at is not None,
        "mfa_enabled": user.mfa_enabled,
        "onboarding_completed": user.onboarding_completed_at is not None,
        "onboarding_state": user.onboarding_state or {},
        "workspaces": [
            {"id": str(ws.id), "name": ws.name, "kind": ws.kind, "role": role,
             "organization_id": str(ws.organization_id), "currency": ws.currency}
            for ws, role in workspaces
        ],
    }


def _session(db, user: User, request: Request) -> dict:
    tokens = accounts.issue_tokens(db, user, request.headers.get("user-agent"), client_ip(request))
    audit.record(db, "auth.login", actor_id=user.id, actor_label=user.email, ip=client_ip(request))
    db.commit()
    return {**tokens, "user": user_out(db, user)}


@router.post("/auth/register", dependencies=[Depends(limit_auth)], status_code=201)
def register(body: RegisterIn, request: Request, db: DB):
    problem = validate_password_strength(body.password)
    if problem:
        raise AppError(problem, code="weak_password")
    user, _ = accounts.create_account(
        db, email=body.email, full_name=body.full_name, account_type=body.account_type,
        organization_name=body.organization_name, password_hash=hash_password(body.password),
    )
    accounts.send_verification(db, user)
    return _session(db, user, request)


@router.post("/auth/login", dependencies=[Depends(limit_auth)])
def login(body: LoginIn, request: Request, db: DB):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        audit.record(db, "auth.login_failed", actor_label=body.email.lower(), ip=client_ip(request))
        db.commit()
        raise Unauthorized("Incorrect email or password.")
    if not user.is_active:
        raise Unauthorized("This account has been deactivated.")
    if user.mfa_enabled:
        return {"mfa_required": True, "mfa_token": create_mfa_challenge(user.id)}
    return _session(db, user, request)


@router.post("/auth/login/mfa", dependencies=[Depends(limit_auth)])
def login_mfa(body: MfaLoginIn, request: Request, db: DB):
    try:
        user = db.get(User, uuid.UUID(decode_token(body.mfa_token, "mfa_challenge")["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthorized("The sign-in attempt expired. Start again.") from exc
    if user is None or not user.mfa_enabled or not user.mfa_secret_encrypted:
        raise Unauthorized("The sign-in attempt expired. Start again.")
    if not pyotp.TOTP(decrypt_secret(user.mfa_secret_encrypted)).verify(body.code.strip(), valid_window=1):
        raise Unauthorized("That code is not correct.")
    return _session(db, user, request)


@router.post("/auth/google", dependencies=[Depends(limit_auth)])
def google_sign_in(body: GoogleIn, request: Request, db: DB):
    settings = get_settings()
    if not settings.google_client_id:
        raise ServiceUnavailable("Google sign-in is not configured.")
    try:
        signing_key = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs").get_signing_key_from_jwt(body.id_token)
        claims = jwt.decode(body.id_token, signing_key.key, algorithms=["RS256"], audience=settings.google_client_id,
                            issuer=["accounts.google.com", "https://accounts.google.com"])
    except jwt.PyJWTError as exc:
        raise Unauthorized("Google sign-in failed.") from exc
    if not claims.get("email_verified"):
        raise Unauthorized("Your Google email address is not verified.")
    user = db.scalar(select(User).where(User.google_sub == claims["sub"])) or db.scalar(
        select(User).where(User.email == claims["email"].lower()))
    if user is None:
        user, _ = accounts.create_account(
            db, email=claims["email"], full_name=claims.get("name", ""), account_type=body.account_type,
            organization_name=body.organization_name or claims.get("name", "My business"),
            google_sub=claims["sub"], verified=True,
        )
    elif user.google_sub is None:
        user.google_sub = claims["sub"]
        user.email_verified_at = user.email_verified_at or utcnow()
    if user.mfa_enabled:
        return {"mfa_required": True, "mfa_token": create_mfa_challenge(user.id)}
    return _session(db, user, request)


@router.post("/auth/refresh")
def refresh(body: RefreshIn, request: Request, db: DB):
    user, tokens = accounts.rotate_refresh_token(db, body.refresh_token, request.headers.get("user-agent"), client_ip(request))
    db.commit()
    return {**tokens, "user": user_out(db, user)}


@router.post("/auth/logout", status_code=204)
def logout(body: RefreshIn, db: DB):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if token and token.revoked_at is None:
        token.revoked_at = utcnow()
        db.commit()


@router.post("/auth/forgot-password", dependencies=[Depends(limit_auth)])
def forgot_password(body: EmailIn, db: DB):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is not None and user.is_active:
        raw = accounts.create_one_time_token(db, user, "reset_password", timedelta(minutes=get_settings().password_reset_minutes))
        link = f"{get_settings().web_origin}/reset-password?token={raw}"
        send_email(user.email, "Reset your MarketingOS password", f"Reset your password: {link}\nThe link expires in an hour.")
        db.commit()
    # Same response either way so the endpoint cannot be used to discover accounts.
    return {"ok": True}


@router.post("/auth/reset-password", dependencies=[Depends(limit_auth)])
def reset_password(body: ResetIn, db: DB):
    problem = validate_password_strength(body.password)
    if problem:
        raise AppError(problem, code="weak_password")
    user = accounts.consume_one_time_token(db, body.token, "reset_password")
    user.password_hash = hash_password(body.password)
    for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        t.revoked_at = utcnow()
    audit.record(db, "auth.password_reset", actor_id=user.id, actor_label=user.email)
    db.commit()
    return {"ok": True}


@router.post("/auth/verify-email")
def verify_email(body: TokenIn, db: DB):
    user = accounts.consume_one_time_token(db, body.token, "verify_email")
    user.email_verified_at = user.email_verified_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/auth/resend-verification")
def resend_verification(user: CurrentUser, db: DB):
    if user.email_verified_at is None:
        accounts.send_verification(db, user)
        db.commit()
    return {"ok": True}


# ---- current user ---------------------------------------------------------------------

class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)


class OnboardingIn(BaseModel):
    state: dict = {}
    completed: bool = False


class CodeIn(BaseModel):
    code: str


class PushDeviceIn(BaseModel):
    token: str = Field(max_length=300)
    platform: Literal["ios", "android"]


@router.get("/users/me")
def me(user: CurrentUser, db: DB):
    return user_out(db, user)


@router.patch("/users/me")
def update_me(body: ProfileIn, user: CurrentUser, db: DB):
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    db.commit()
    return user_out(db, user)


@router.post("/users/me/onboarding")
def save_onboarding(body: OnboardingIn, user: CurrentUser, db: DB):
    user.onboarding_state = {**(user.onboarding_state or {}), **body.state}
    if body.completed:
        user.onboarding_completed_at = user.onboarding_completed_at or utcnow()
    db.commit()
    return user_out(db, user)


@router.post("/users/me/mfa/setup")
def mfa_setup(user: CurrentUser, db: DB):
    if user.mfa_enabled:
        raise AppError("Two-factor authentication is already on.")
    secret = pyotp.random_base32()
    user.mfa_secret_encrypted = encrypt_secret(secret)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="MarketingOS")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/users/me/mfa/enable")
def mfa_enable(body: CodeIn, user: CurrentUser, db: DB):
    if not user.mfa_secret_encrypted:
        raise AppError("Start setup first.")
    if not pyotp.TOTP(decrypt_secret(user.mfa_secret_encrypted)).verify(body.code.strip(), valid_window=1):
        raise AppError("That code is not correct.", code="invalid_code")
    user.mfa_enabled = True
    audit.record(db, "auth.mfa_enabled", actor_id=user.id, actor_label=user.email)
    db.commit()
    return {"ok": True}


@router.post("/users/me/mfa/disable")
def mfa_disable(body: CodeIn, user: CurrentUser, db: DB):
    if not user.mfa_enabled or not pyotp.TOTP(decrypt_secret(user.mfa_secret_encrypted)).verify(body.code.strip(), valid_window=1):
        raise AppError("That code is not correct.", code="invalid_code")
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    audit.record(db, "auth.mfa_disabled", actor_id=user.id, actor_label=user.email)
    db.commit()
    return {"ok": True}


@router.delete("/users/me", status_code=204)
def delete_me(user: CurrentUser, db: DB):
    """Deletes the user's personal data. Owners must delete or transfer their organization first."""
    if db.scalar(select(Organization).where(Organization.owner_id == user.id)):
        raise Forbidden("You own an organization. Delete its workspaces or transfer ownership first.")
    audit.record(db, "account.deleted", actor_id=user.id, actor_label="deleted-user")
    db.delete(user)
    db.commit()


@router.get("/notifications")
def notifications(user: CurrentUser, db: DB, unread: bool = False, limit: int = 50):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(min(limit, 200))).all()
    return [
        {"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "data": n.data,
         "workspace_id": str(n.workspace_id) if n.workspace_id else None, "read": n.read_at is not None,
         "created_at": n.created_at}
        for n in rows
    ]


@router.post("/notifications/read-all")
def read_all(user: CurrentUser, db: DB):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))):
        n.read_at = utcnow()
    db.commit()
    return {"ok": True}


@router.post("/users/me/push-devices", status_code=201)
def register_push_device(body: PushDeviceIn, user: CurrentUser, db: DB):
    device = db.scalar(select(PushDevice).where(PushDevice.token == body.token))
    if device is None:
        db.add(PushDevice(user_id=user.id, token=body.token, platform=body.platform))
    else:
        device.user_id = user.id
    db.commit()
    return {"ok": True}
