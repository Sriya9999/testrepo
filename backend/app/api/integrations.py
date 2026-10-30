import uuid
from typing import Literal
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, load_workspace_context, require
from app.errors import AppError, NotFound, ServiceUnavailable
from app.models import ConnectedAccount, IntegrationSyncLog, User
from app.providers import google, meta
from app.security import create_state_token, decode_token
from app.services import audit, integrations, jobs

router = APIRouter(tags=["integrations"])


class ConnectIn(BaseModel):
    mode: Literal["live", "sandbox"] = "live"
    label: str | None = None
    credentials: dict | None = None  # wordpress / shopify


def _catalog(db, ctx) -> list[dict]:
    accounts = db.scalars(select(ConnectedAccount).where(ConnectedAccount.workspace_id == ctx.workspace_id)).all()
    settings = get_settings()
    out = []
    for key, info in integrations.CATALOG.items():
        mine = [a for a in accounts if a.provider == key and a.status != "disconnected"]
        out.append({
            "provider": key, **info, "configured": integrations.provider_configured(key),
            "sandbox_available": settings.allow_sandbox_integrations and info["auth"] != "credentials",
            "status": ("error" if any(a.status == "error" for a in mine) else "connected") if mine else "not_connected",
            "accounts": [integrations.account_out(a) for a in mine],
            "last_sync_at": max((a.last_sync_at for a in mine if a.last_sync_at), default=None),
        })
    out.append({
        "provider": "ai", "name": "AI providers", "category": "ai", "auth": "server",
        "description": "Text, image and AI-search providers configured by the platform operator.",
        "configured": True, "sandbox_available": False, "status": "connected", "accounts": [],
        "details": {
            "text": settings.ai_provider, "openai": bool(settings.openai_api_key),
            "perplexity": bool(settings.perplexity_api_key), "pagespeed": True,
            "keyword_data": "google_ads" if settings.google_ads_developer_token else (
                "dataforseo" if settings.dataforseo_login else None),
        },
    })
    return out


@router.get("/integrations")
def list_integrations(ctx: Ctx, db: DB):
    return _catalog(db, ctx)


@router.post("/integrations/{provider}/connect")
def connect(provider: str, body: ConnectIn, db: DB, ctx: WorkspaceContext = require("integrations:manage")):
    if provider not in integrations.CATALOG:
        raise NotFound("Unknown integration")
    auth = integrations.CATALOG[provider]["auth"]
    if body.mode == "sandbox":
        created = integrations.connect_sandbox(db, ctx.workspace_id, provider, ctx.user.id, body.label)
    elif auth == "credentials":
        created = integrations.connect_credentials(db, ctx.workspace_id, provider, ctx.user.id, body.credentials or {})
    else:
        if not integrations.provider_configured(provider):
            raise ServiceUnavailable(
                f"{integrations.CATALOG[provider]['name']} is not configured on this server yet. "
                "Use a sandbox connection to try the workflow.", code="integration_not_configured")
        state = create_state_token({"ws": str(ctx.workspace_id), "uid": str(ctx.user.id), "provider": provider})
        redirect = integrations.callback_url(provider)
        if auth == "meta_oauth":
            scopes = meta.SCOPES_INSTAGRAM if provider == "instagram" else meta.SCOPES_ADS
            url = meta.authorize_url(redirect, state, scopes)
        else:
            url = google.authorize_url(provider, redirect, state)
        return {"authorize_url": url}
    for a in created:
        audit.record(db, "integration.connected", ctx=ctx, resource_type="connected_account", resource_id=a.id,
                     data={"provider": provider, "mode": a.mode})
    db.commit()
    return {"accounts": [integrations.account_out(a) for a in created]}


@router.get("/integrations/{provider}/callback", include_in_schema=False)
def oauth_callback(provider: str, db: DB, state: str, code: str | None = None, error: str | None = None):
    web = get_settings().web_origin.rstrip("/")
    try:
        data = decode_token(state, "oauth_state")
    except jwt.PyJWTError:
        return RedirectResponse(f"{web}/integrations?{urlencode({'error': 'The connection request expired. Try again.'})}")
    if data.get("provider") != provider:
        return RedirectResponse(f"{web}/integrations?{urlencode({'error': 'Invalid connection request.'})}")
    if error or not code:
        return RedirectResponse(f"{web}/integrations?{urlencode({'error': error or 'Connection cancelled.'})}")
    user = db.get(User, uuid.UUID(data["uid"]))
    try:
        ctx = load_workspace_context(db, user, data["ws"])
        ctx.require("integrations:manage")
        created = integrations.complete_oauth(db, provider, ctx.workspace_id, user.id, code)
        for a in created:
            audit.record(db, "integration.connected", ctx=ctx, resource_type="connected_account", resource_id=a.id,
                         data={"provider": provider, "mode": "live"})
            jobs.enqueue(db, "integration.sync", {"account_id": a.id}, workspace_id=ctx.workspace_id)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the user
        db.rollback()
        return RedirectResponse(f"{web}/integrations?{urlencode({'error': str(exc)[:300]})}")
    return RedirectResponse(f"{web}/integrations?{urlencode({'connected': provider})}")


@router.get("/integrations/accounts")
def list_accounts(ctx: Ctx, db: DB, provider: str | None = None):
    stmt = select(ConnectedAccount).where(ConnectedAccount.workspace_id == ctx.workspace_id,
                                          ConnectedAccount.status != "disconnected")
    if provider:
        stmt = stmt.where(ConnectedAccount.provider == provider)
    return [integrations.account_out(a) for a in db.scalars(stmt.order_by(ConnectedAccount.created_at))]


@router.get("/integrations/instagram/accounts")
def instagram_accounts(ctx: Ctx, db: DB):
    return list_accounts(ctx, db, "instagram")


@router.post("/integrations/instagram/connect")
def instagram_connect(body: ConnectIn, db: DB, ctx: WorkspaceContext = require("integrations:manage")):
    return connect("instagram", body, db, ctx)


@router.delete("/integrations/accounts/{account_id}", status_code=204)
@router.delete("/integrations/instagram/accounts/{account_id}", status_code=204, include_in_schema=False)
def disconnect(account_id: str, db: DB, ctx: WorkspaceContext = require("integrations:manage")):
    account = get_or_404(db, ConnectedAccount, account_id, ctx, "Connected account")
    integrations.disconnect(db, account)
    audit.record(db, "integration.disconnected", ctx=ctx, resource_type="connected_account", resource_id=account.id,
                 data={"provider": account.provider})
    db.commit()


@router.post("/integrations/accounts/{account_id}/sync", status_code=202)
def sync_account(account_id: str, db: DB, ctx: WorkspaceContext = require("integrations:read")):
    account = get_or_404(db, ConnectedAccount, account_id, ctx, "Connected account")
    if account.status == "disconnected":
        raise AppError("Reconnect this account first.")
    job = jobs.enqueue(db, "integration.sync", {"account_id": account.id}, workspace_id=ctx.workspace_id, created_by=ctx.user.id)
    db.commit()
    return {"job_id": str(job.id)}


@router.get("/integrations/accounts/{account_id}/logs")
def sync_logs(account_id: str, ctx: Ctx, db: DB):
    account = get_or_404(db, ConnectedAccount, account_id, ctx, "Connected account")
    rows = db.scalars(select(IntegrationSyncLog).where(IntegrationSyncLog.connected_account_id == account.id)
                      .order_by(IntegrationSyncLog.created_at.desc()).limit(50))
    return [{"operation": r.operation, "status": r.status, "message": r.message, "records": r.records,
             "created_at": r.created_at} for r in rows]


@router.get("/integrations/health")
def integration_health(ctx: Ctx, db: DB):
    """Data freshness and integration errors for the dashboard (FR-DASH-007)."""
    rows = db.scalars(select(ConnectedAccount).where(ConnectedAccount.workspace_id == ctx.workspace_id,
                                                     ConnectedAccount.status != "disconnected")).all()
    now = utcnow()
    out = []
    for a in rows:
        last = a.last_sync_at
        from app.db import as_aware

        age_hours = round((now - as_aware(last)).total_seconds() / 3600, 1) if last else None
        out.append({"id": str(a.id), "provider": a.provider, "name": a.display_name, "mode": a.mode, "status": a.status,
                    "last_sync_at": last, "age_hours": age_hours, "stale": age_hours is None or age_hours > 36,
                    "error": a.last_error})
    return out
