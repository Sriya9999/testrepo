"""Connected accounts and the encrypted token vault."""

import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_aware, utcnow
from app.errors import AppError, IntegrationRequired, ServiceUnavailable
from app.models import AdAccount, ConnectedAccount, IntegrationSyncLog, OAuthToken
from app.providers import google, meta
from app.security import decrypt_secret, encrypt_secret

CATALOG = {
    "instagram": {"name": "Instagram", "category": "social", "auth": "meta_oauth",
                  "description": "Publish and measure posts, carousels, Reels and Stories on Instagram Professional accounts."},
    "meta": {"name": "Meta Business (Ads)", "category": "advertising", "auth": "meta_oauth",
             "description": "Ad accounts, Pages and Instagram identities for Facebook and Instagram ads."},
    "google_ads": {"name": "Google Ads", "category": "advertising", "auth": "google_oauth",
                   "description": "Search campaigns, keyword planning and performance."},
    "google_analytics": {"name": "Google Analytics 4", "category": "analytics", "auth": "google_oauth",
                         "description": "Sessions, channels and conversions."},
    "search_console": {"name": "Search Console", "category": "search", "auth": "google_oauth",
                       "description": "Organic queries, clicks, impressions and positions."},
    "wordpress": {"name": "WordPress", "category": "website", "auth": "credentials",
                  "description": "Connect with an application password to publish articles."},
    "shopify": {"name": "Shopify", "category": "website", "auth": "credentials",
                "description": "Connect a store with an Admin API access token."},
}


def provider_configured(provider: str) -> bool:
    s = get_settings()
    auth = CATALOG[provider]["auth"]
    if auth == "meta_oauth":
        return bool(s.meta_app_id and s.meta_app_secret)
    if auth == "google_oauth":
        ok = bool(s.google_client_id and s.google_client_secret)
        return ok and (provider != "google_ads" or bool(s.google_ads_developer_token))
    return True


def callback_url(provider: str) -> str:
    return f"{get_settings().public_api_url.rstrip('/')}{get_settings().api_prefix}/integrations/{provider}/callback"


def store_token(db: Session, account: ConnectedAccount, access_token: str, refresh_token: str | None,
                expires_in: int | None) -> None:
    token = db.scalar(select(OAuthToken).where(OAuthToken.connected_account_id == account.id))
    if token is None:
        token = OAuthToken(connected_account_id=account.id, access_token_encrypted="")
        db.add(token)
    token.access_token_encrypted = encrypt_secret(access_token)
    if refresh_token:
        token.refresh_token_encrypted = encrypt_secret(refresh_token)
    token.expires_at = utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None


def access_token(db: Session, account: ConnectedAccount) -> str:
    """Return a usable access token, refreshing Google tokens when they are about to expire."""
    if account.status == "disconnected":
        raise IntegrationRequired(f"{CATALOG[account.provider]['name']} is disconnected.")
    token = db.scalar(select(OAuthToken).where(OAuthToken.connected_account_id == account.id))
    if token is None:
        raise IntegrationRequired(f"{CATALOG[account.provider]['name']} needs to be reconnected.")
    expires = as_aware(token.expires_at)
    if CATALOG[account.provider]["auth"] == "google_oauth" and expires and expires < utcnow() + timedelta(minutes=5):
        if not token.refresh_token_encrypted:
            raise IntegrationRequired("Google access expired. Reconnect the account.")
        fresh = google.refresh(decrypt_secret(token.refresh_token_encrypted))
        store_token(db, account, fresh["access_token"], fresh.get("refresh_token"), fresh.get("expires_in"))
        return fresh["access_token"]
    return decrypt_secret(token.access_token_encrypted)


def log_sync(db: Session, account: ConnectedAccount | None, workspace_id: uuid.UUID, provider: str, operation: str,
             ok: bool, message: str = "", records: int = 0) -> None:
    db.add(IntegrationSyncLog(
        workspace_id=workspace_id, connected_account_id=account.id if account else None, provider=provider,
        operation=operation, status="success" if ok else "error", message=message[:2000], records=records,
    ))
    if account is not None:
        if ok:
            account.last_sync_at = utcnow()
            account.last_error = None
            if account.status == "error":
                account.status = "connected"
        else:
            account.last_error = message[:2000]
            account.status = "error"


def _upsert_account(db: Session, workspace_id: uuid.UUID, provider: str, external_id: str, display_name: str,
                    mode: str, details: dict, user_id: uuid.UUID | None, scopes: list[str] | None = None) -> ConnectedAccount:
    account = db.scalar(select(ConnectedAccount).where(
        ConnectedAccount.workspace_id == workspace_id, ConnectedAccount.provider == provider,
        ConnectedAccount.external_id == external_id))
    if account is None:
        account = ConnectedAccount(workspace_id=workspace_id, provider=provider, external_id=external_id)
        db.add(account)
    account.display_name = display_name
    account.mode = mode
    account.status = "connected"
    account.details = details
    account.scopes = scopes or []
    account.connected_by = user_id
    account.last_error = None
    db.flush()
    return account


def _upsert_ad_account(db: Session, workspace_id: uuid.UUID, account: ConnectedAccount, platform: str, external_id: str,
                       name: str, currency: str, timezone: str | None, details: dict | None = None) -> AdAccount:
    row = db.scalar(select(AdAccount).where(AdAccount.workspace_id == workspace_id, AdAccount.platform == platform,
                                            AdAccount.external_id == external_id))
    if row is None:
        row = AdAccount(workspace_id=workspace_id, platform=platform, external_id=external_id,
                        connected_account_id=account.id, name=name)
        db.add(row)
    row.connected_account_id = account.id
    row.name, row.currency, row.timezone = name, currency or "INR", timezone
    row.details = details or {}
    row.status = "active"
    return row


def connect_sandbox(db: Session, workspace_id: uuid.UUID, provider: str, user_id: uuid.UUID, label: str | None) -> list[ConnectedAccount]:
    if not get_settings().allow_sandbox_integrations:
        raise AppError("Sandbox connections are disabled in this environment.")
    name = label or {"instagram": "sandbox.brand", "meta": "Sandbox Ad Account",
                     "google_ads": "Sandbox Google Ads", "search_console": "sc-domain:example.com",
                     "google_analytics": "Sandbox GA4 property"}.get(provider, f"Sandbox {provider}")
    ext = f"sandbox-{provider}-{uuid.uuid4().hex[:8]}"
    details = {"sandbox": True, "note": "Sandbox: actions are recorded locally and never sent to the platform."}
    if provider == "instagram":
        details.update({"username": name, "ig_user_id": ext, "page_id": f"{ext}-page"})
    account = _upsert_account(db, workspace_id, provider, ext, name, "sandbox", details, user_id)
    if provider in ("meta", "google_ads"):
        platform = "meta" if provider == "meta" else "google"
        _upsert_ad_account(db, workspace_id, account, platform, ext, name, "INR", "Asia/Kolkata",
                           {"pages": [{"id": f"{ext}-page", "name": f"{name} Page"}], "sandbox": True})
    return [account]


def connect_credentials(db: Session, workspace_id: uuid.UUID, provider: str, user_id: uuid.UUID, creds: dict) -> list[ConnectedAccount]:
    if provider == "wordpress":
        site = (creds.get("site_url") or "").rstrip("/")
        user, password = creds.get("username"), creds.get("application_password")
        if not (site.startswith("https://") and user and password):
            raise AppError("WordPress needs an https site URL, a username and an application password.")
        try:
            resp = httpx.get(f"{site}/wp-json/wp/v2/users/me", auth=(user, password), timeout=20)
        except httpx.HTTPError as exc:
            raise AppError(f"Could not reach {site}: {exc}") from exc
        if resp.status_code != 200:
            raise AppError("WordPress rejected those credentials.")
        account = _upsert_account(db, workspace_id, "wordpress", site, site, "live", {"username": user}, user_id)
        store_token(db, account, f"{user}:{password}", None, None)
        return [account]
    if provider == "shopify":
        shop = (creds.get("shop_domain") or "").strip().lower()
        token = creds.get("access_token")
        if not (shop.endswith(".myshopify.com") and token):
            raise AppError("Shopify needs a *.myshopify.com domain and an Admin API access token.")
        try:
            resp = httpx.get(f"https://{shop}/admin/api/2024-10/shop.json", headers={"X-Shopify-Access-Token": token}, timeout=20)
        except httpx.HTTPError as exc:
            raise AppError(f"Could not reach {shop}: {exc}") from exc
        if resp.status_code != 200:
            raise AppError("Shopify rejected that access token.")
        info = resp.json().get("shop", {})
        account = _upsert_account(db, workspace_id, "shopify", shop, info.get("name", shop), "live",
                                  {"currency": info.get("currency")}, user_id)
        store_token(db, account, token, None, None)
        return [account]
    raise AppError(f"{provider} does not use credential connections")


def complete_oauth(db: Session, provider: str, workspace_id: uuid.UUID, user_id: uuid.UUID, code: str) -> list[ConnectedAccount]:
    if not provider_configured(provider):
        raise ServiceUnavailable(f"{CATALOG[provider]['name']} is not configured on this server.")
    redirect = callback_url(provider)
    created: list[ConnectedAccount] = []
    if CATALOG[provider]["auth"] == "meta_oauth":
        tok = meta.exchange_code(code, redirect)
        client = meta.MetaClient(tok["access_token"])
        if provider == "instagram":
            for ig in client.instagram_accounts():
                acct = _upsert_account(db, workspace_id, "instagram", ig["id"], f"@{ig.get('username', ig['id'])}", "live",
                                       {"username": ig.get("username"), "ig_user_id": ig["id"], "page_id": ig["page_id"],
                                        "page_name": ig.get("page_name"), "followers_count": ig.get("followers_count"),
                                        "profile_picture_url": ig.get("profile_picture_url")},
                                       user_id, meta.SCOPES_INSTAGRAM)
                store_token(db, acct, tok["access_token"], None, tok.get("expires_in"))
                created.append(acct)
            if not created:
                raise AppError("No Instagram Professional account is linked to the Facebook Pages you granted. "
                               "Convert the account to Business or Creator and link it to a Page.")
        else:
            me = client.me()
            pages = [{"id": p["id"], "name": p.get("name"),
                      "instagram_user_id": (p.get("instagram_business_account") or {}).get("id")} for p in client.pages()]
            acct = _upsert_account(db, workspace_id, "meta", me["id"], me.get("name", "Meta"), "live",
                                   {"pages": pages}, user_id, meta.SCOPES_ADS)
            store_token(db, acct, tok["access_token"], None, tok.get("expires_in"))
            for ad in client.ad_accounts():
                _upsert_ad_account(db, workspace_id, acct, "meta", ad["account_id"], ad.get("name", ad["account_id"]),
                                   ad.get("currency", "INR"), ad.get("timezone_name"), {"pages": pages,
                                                                                         "account_status": ad.get("account_status")})
            created.append(acct)
        return created

    tok = google.exchange_code(code, redirect)
    access = tok["access_token"]
    if provider == "google_ads":
        client = google.GoogleAdsClient(access)
        customers = client.accessible_customers()
        acct = _upsert_account(db, workspace_id, "google_ads", ",".join(customers) or "none", "Google Ads", "live",
                               {"customers": customers}, user_id, google.SCOPES["google_ads"])
        store_token(db, acct, access, tok.get("refresh_token"), tok.get("expires_in"))
        for cid in customers:
            try:
                info = client.customer_info(cid)
            except google.GoogleError:
                continue
            if info.get("manager"):
                continue
            _upsert_ad_account(db, workspace_id, acct, "google", cid, info.get("descriptiveName") or cid,
                               info.get("currencyCode", "INR"), info.get("timeZone"))
        return [acct]
    if provider == "search_console":
        sites = google.search_console_sites(access)
        acct = _upsert_account(db, workspace_id, "search_console", "search_console", "Search Console", "live",
                               {"sites": [s["siteUrl"] for s in sites]}, user_id, google.SCOPES["search_console"])
        store_token(db, acct, access, tok.get("refresh_token"), tok.get("expires_in"))
        return [acct]
    props = google.analytics_properties(access)
    acct = _upsert_account(db, workspace_id, "google_analytics", "google_analytics", "Google Analytics", "live",
                           {"properties": props}, user_id, google.SCOPES["google_analytics"])
    store_token(db, acct, access, tok.get("refresh_token"), tok.get("expires_in"))
    return [acct]


def disconnect(db: Session, account: ConnectedAccount) -> None:
    token = db.scalar(select(OAuthToken).where(OAuthToken.connected_account_id == account.id))
    if token is not None:
        db.delete(token)
    account.status = "disconnected"
    for ad in db.scalars(select(AdAccount).where(AdAccount.connected_account_id == account.id)):
        ad.status = "disconnected"


def account_out(a: ConnectedAccount) -> dict:
    return {
        "id": str(a.id), "provider": a.provider, "provider_name": CATALOG.get(a.provider, {}).get("name", a.provider),
        "external_id": a.external_id, "display_name": a.display_name, "mode": a.mode, "status": a.status,
        "scopes": a.scopes, "details": {k: v for k, v in (a.details or {}).items() if "token" not in k.lower()},
        "last_sync_at": a.last_sync_at, "last_error": a.last_error, "created_at": a.created_at,
    }
