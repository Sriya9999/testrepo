"""Integration sync jobs: pull measured data from connected platforms."""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    AdAccount,
    ConnectedAccount,
    Job,
    Keyword,
    KeywordRanking,
    PerformanceSnapshot,
    SocialPost,
    Website,
    Workspace,
)
from app.providers import google, meta
from app.services import integrations, jobs


def _snapshot(db: Session, workspace_id, channel: str, day: date, source: str, **values) -> None:
    row = db.scalar(select(PerformanceSnapshot).where(PerformanceSnapshot.workspace_id == workspace_id, PerformanceSnapshot.channel == channel,
                                                      PerformanceSnapshot.date == day, PerformanceSnapshot.source == source))
    if row is None:
        row = PerformanceSnapshot(workspace_id=workspace_id, channel=channel, date=day, source=source)
        db.add(row)
    for k, v in values.items():
        setattr(row, k, v)


@jobs.handler("integration.sync")
def sync_account(db: Session, job: Job) -> dict:
    account = db.get(ConnectedAccount, uuid.UUID(job.payload["account_id"]))
    if account is None or account.status == "disconnected":
        return {"skipped": True}
    if account.mode == "sandbox":
        integrations.log_sync(db, account, account.workspace_id, account.provider, "sync", True,
                              "Sandbox account: nothing to fetch; no metrics are generated.")
        db.commit()
        return {"sandbox": True}
    handler = {"instagram": _sync_instagram, "meta": _sync_ads, "google_ads": _sync_ads, "search_console": _sync_search_console,
               "google_analytics": _sync_analytics}.get(account.provider)
    if handler is None:
        integrations.log_sync(db, account, account.workspace_id, account.provider, "sync", True, "Nothing to sync for this integration.")
        db.commit()
        return {}
    try:
        count = handler(db, account)
        integrations.log_sync(db, account, account.workspace_id, account.provider, "sync", True, records=count)
        db.commit()
        return {"records": count}
    except (meta.MetaError, google.GoogleError) as exc:
        db.rollback()
        account = db.get(ConnectedAccount, account.id)
        integrations.log_sync(db, account, account.workspace_id, account.provider, "sync", False, str(exc))
        db.commit()
        raise


def _sync_instagram(db: Session, account: ConnectedAccount) -> int:
    client = meta.MetaClient(integrations.access_token(db, account))
    ig = account.details.get("ig_user_id") or account.external_id
    info = client.account_insights(ig)
    _snapshot(db, account.workspace_id, "instagram", date.today(), "instagram", followers=info.get("followers_count"))
    since = utcnow() - timedelta(days=60)
    count = 0
    for post in db.scalars(select(SocialPost).where(SocialPost.connected_account_id == account.id, SocialPost.status == "published",
                                                    SocialPost.external_id.is_not(None), SocialPost.published_at >= since)):
        try:
            post.metrics = client.media_insights(post.external_id)
            post.metrics_source = "instagram"
            count += 1
        except meta.MetaError:
            continue
    return count


def _sync_ads(db: Session, account: ConnectedAccount) -> int:
    n = 0
    for acct in db.scalars(select(AdAccount).where(AdAccount.connected_account_id == account.id, AdAccount.status == "active")):
        jobs.enqueue(db, "ads.sync", {"ad_account_id": acct.id, "days": 30}, workspace_id=account.workspace_id)
        n += 1
    return n


def _sync_search_console(db: Session, account: ConnectedAccount) -> int:
    token = integrations.access_token(db, account)
    until = date.today() - timedelta(days=3)  # Search Console data lags ~2-3 days
    since = until - timedelta(days=28)
    count = 0
    for site in db.scalars(select(Website).where(Website.workspace_id == account.workspace_id, Website.search_console_property.is_not(None))):
        for row in google.search_console_query(token, site.search_console_property, since, until, ["date"]):
            _snapshot(db, account.workspace_id, "organic", date.fromisoformat(row["keys"][0]), "search_console",
                      clicks=int(row.get("clicks", 0)), impressions=int(row.get("impressions", 0)), avg_position=row.get("position"))
            count += 1
        tracked = {k.text: k for k in db.scalars(select(Keyword).where(Keyword.website_id == site.id))}
        if tracked:
            for row in google.search_console_query(token, site.search_console_property, since, until, ["date", "query", "page"]):
                day, query, page = row["keys"]
                k = tracked.get(query.lower())
                if k is None:
                    continue
                existing = db.scalar(select(KeywordRanking).where(KeywordRanking.keyword_id == k.id, KeywordRanking.date == date.fromisoformat(day),
                                                                  KeywordRanking.source == "search_console"))
                if existing is None or (row.get("position") or 999) < (existing.position or 999):
                    if existing is None:
                        existing = KeywordRanking(workspace_id=k.workspace_id, keyword_id=k.id, date=date.fromisoformat(day), source="search_console")
                        db.add(existing)
                    existing.position, existing.clicks, existing.impressions, existing.url = (
                        row.get("position"), int(row.get("clicks", 0)), int(row.get("impressions", 0)), page)
                    count += 1
    return count


def _sync_analytics(db: Session, account: ConnectedAccount) -> int:
    token = integrations.access_token(db, account)
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=28)
    count = 0
    for site in db.scalars(select(Website).where(Website.workspace_id == account.workspace_id, Website.analytics_property.is_not(None))):
        totals: dict = {}
        for row in google.analytics_daily(token, site.analytics_property, since, until):
            if row["channel"] != "Organic Search":
                continue
            d = date(int(row["date"][:4]), int(row["date"][4:6]), int(row["date"][6:]))
            t = totals.setdefault(d, {"sessions": 0, "users": 0, "conversions": 0, "revenue_minor": 0})
            t["sessions"] += row["sessions"]
            t["users"] += row["users"]
            t["conversions"] += row["conversions"]
            t["revenue_minor"] += round(row["revenue"] * 100)
        for d, t in totals.items():
            _snapshot(db, account.workspace_id, "website", d, "ga4", **t)
            count += 1
    return count


@jobs.handler("workspace.purge")
def purge_workspace(db: Session, job: Job) -> dict:
    ws = db.get(Workspace, uuid.UUID(job.payload["workspace_id"]))
    if ws is None or ws.status != "pending_deletion":
        return {"skipped": True}
    from app.models import Client

    for c in db.scalars(select(Client).where(Client.agency_workspace_id == ws.id)):
        child = db.get(Workspace, c.client_workspace_id)
        if child:
            db.delete(child)
    db.delete(ws)
    db.commit()
    return {"purged": str(job.payload["workspace_id"])}


def enqueue_daily_syncs(db: Session) -> int:
    count = 0
    threshold = utcnow() - timedelta(hours=20)
    for a in db.scalars(select(ConnectedAccount).where(ConnectedAccount.status != "disconnected", ConnectedAccount.mode == "live")):
        if a.last_sync_at is None or a.last_sync_at.replace(tzinfo=threshold.tzinfo) < threshold:
            exists = db.scalar(select(Job).where(Job.type == "integration.sync", Job.status.in_(["queued", "running"]),
                                                 Job.payload["account_id"].as_string() == str(a.id)))
            if exists is None:
                jobs.enqueue(db, "integration.sync", {"account_id": a.id}, workspace_id=a.workspace_id)
                count += 1
    db.commit()
    return count
