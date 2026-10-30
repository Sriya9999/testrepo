import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import as_aware, utcnow
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.engines.content_formats import LIMITS
from app.errors import AppError, Conflict
from app.models import Approval, ConnectedAccount, ContentAsset, Job, MediaAsset, PerformanceSnapshot, SocialPost, User
from app.providers import meta
from app.services import approvals, audit, integrations, jobs, storage
from app.services.approvals import ActionSpec, register_action
from app.services.jobs import RetryableError

router = APIRouter(tags=["social"])

EDITABLE = {"draft", "changes_requested", "rejected", "failed", "cancelled"}
MIN_LEAD = timedelta(minutes=2)


class PostIn(BaseModel):
    connected_account_id: uuid.UUID | None = None
    content_asset_id: uuid.UUID | None = None
    format: Literal["image", "carousel", "reel", "story"] = "image"
    caption: str | None = Field(default=None, max_length=2200)
    media_asset_ids: list[uuid.UUID] = []
    scheduled_at: datetime | None = None


class PostPatch(BaseModel):
    connected_account_id: uuid.UUID | None = None
    format: Literal["image", "carousel", "reel", "story"] | None = None
    caption: str | None = Field(default=None, max_length=2200)
    media_asset_ids: list[uuid.UUID] | None = None
    scheduled_at: datetime | None = None


class ScheduleIn(BaseModel):
    scheduled_at: datetime | None = None


def post_out(p: SocialPost, account: ConnectedAccount | None = None) -> dict:
    return {
        "id": str(p.id), "platform": p.platform, "format": p.format, "caption": p.caption, "media": p.media,
        "scheduled_at": as_aware(p.scheduled_at), "status": p.status,
        "connected_account_id": str(p.connected_account_id) if p.connected_account_id else None,
        "account": {"name": account.display_name, "mode": account.mode} if account else None,
        "content_asset_id": str(p.content_asset_id) if p.content_asset_id else None,
        "approval_id": str(p.approval_id) if p.approval_id else None, "external_id": p.external_id,
        "permalink": p.permalink, "attempts": p.attempts, "last_error": p.last_error,
        "published_at": as_aware(p.published_at), "metrics": p.metrics, "metrics_source": p.metrics_source,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def _media(db: Session, ctx, ids: list[uuid.UUID]) -> list[dict]:
    out = []
    for mid in ids:
        m = get_or_404(db, MediaAsset, mid, ctx, "Media")
        out.append({"media_asset_id": str(m.id), "url": storage.public_url(m.storage_key), "kind": m.kind,
                    "mime_type": m.mime_type})
    return out


def caption_from_content(asset: ContentAsset) -> str:
    body = asset.body or {}
    caption = body.get("caption") or body.get("primary_text") or body.get("short_answer") or ""
    tags = " ".join(body.get("hashtags") or [])
    return f"{caption}\n\n{tags}".strip() if tags and tags not in caption else caption


@router.post("/social/posts", status_code=201)
def create_post(body: PostIn, db: DB, ctx: WorkspaceContext = require("social:write")):
    caption = body.caption or ""
    media = _media(db, ctx, body.media_asset_ids)
    if body.content_asset_id:
        asset = get_or_404(db, ContentAsset, body.content_asset_id, ctx, "Content")
        caption = caption or caption_from_content(asset)
        media = media or [m for m in (asset.body or {}).get("media", [])]
    if body.connected_account_id:
        get_or_404(db, ConnectedAccount, body.connected_account_id, ctx, "Account")
    post = SocialPost(
        workspace_id=ctx.workspace_id, connected_account_id=body.connected_account_id,
        content_asset_id=body.content_asset_id, format=body.format, caption=caption, media=media,
        scheduled_at=body.scheduled_at, created_by=ctx.user.id,
    )
    db.add(post)
    db.commit()
    return post_out(post)


@router.get("/social/posts")
def list_posts(ctx: Ctx, db: DB, start: datetime | None = None, end: datetime | None = None, status: str | None = None,
               account_id: uuid.UUID | None = None, limit: int = 300):
    ctx.require("social:read")
    stmt = select(SocialPost).where(SocialPost.workspace_id == ctx.workspace_id)
    if start:
        stmt = stmt.where((SocialPost.scheduled_at >= start) | (SocialPost.published_at >= start))
    if end:
        stmt = stmt.where((SocialPost.scheduled_at < end) | (SocialPost.published_at < end))
    if status:
        stmt = stmt.where(SocialPost.status == status)
    if account_id:
        stmt = stmt.where(SocialPost.connected_account_id == account_id)
    accounts = {a.id: a for a in db.scalars(select(ConnectedAccount).where(ConnectedAccount.workspace_id == ctx.workspace_id))}
    rows = db.scalars(stmt.order_by(SocialPost.scheduled_at.is_(None), SocialPost.scheduled_at, SocialPost.created_at.desc())
                      .limit(min(limit, 1000)))
    return [post_out(p, accounts.get(p.connected_account_id)) for p in rows]


@router.get("/social/posts/{post_id}")
def get_post(post_id: str, ctx: Ctx, db: DB):
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    account = db.get(ConnectedAccount, post.connected_account_id) if post.connected_account_id else None
    return post_out(post, account)


def _supersede_pending(db: Session, post: SocialPost) -> None:
    for a in db.scalars(select(Approval).where(Approval.resource_id == post.id, Approval.status == "pending")):
        a.status = "superseded"


@router.patch("/social/posts/{post_id}")
def edit_post(post_id: str, body: PostPatch, db: DB, ctx: WorkspaceContext = require("social:write")):
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    if post.status in ("publishing", "published"):
        raise Conflict("Published posts cannot be edited here.")
    changes = body.model_dump(exclude_unset=True)
    content_change = any(k in changes for k in ("caption", "media_asset_ids", "format", "connected_account_id"))
    if "connected_account_id" in changes and changes["connected_account_id"]:
        get_or_404(db, ConnectedAccount, changes["connected_account_id"], ctx, "Account")
        post.connected_account_id = changes["connected_account_id"]
    if "caption" in changes:
        post.caption = changes["caption"] or ""
    if "format" in changes:
        post.format = changes["format"]
    if "media_asset_ids" in changes:
        post.media = _media(db, ctx, changes["media_asset_ids"] or [])
    if content_change and post.status not in EDITABLE:
        # Approved content changed: it must be approved again before it can go out.
        _supersede_pending(db, post)
        post.status = "draft"
        post.approval_id = None
    if "scheduled_at" in changes:
        new_time = changes["scheduled_at"]
        if post.status == "scheduled":
            ctx.require("social:schedule")
            if new_time is None or as_aware(new_time) < utcnow() + MIN_LEAD:
                raise AppError("Choose a time at least 2 minutes from now.")
            audit.record(db, "social.rescheduled", ctx=ctx, resource_type="social_post", resource_id=post.id,
                         data={"from": str(post.scheduled_at), "to": str(new_time)})
        elif post.status in ("in_review", "approved") and not content_change:
            _supersede_pending(db, post)
            post.status = "draft"
        post.scheduled_at = new_time
    db.commit()
    return post_out(post)


def _validate_for_publish(db: Session, post: SocialPost, scheduled_at: datetime | None) -> ConnectedAccount:
    if not post.connected_account_id:
        raise AppError("Choose an Instagram account first.")
    account = db.get(ConnectedAccount, post.connected_account_id)
    if account is None or account.status == "disconnected":
        raise AppError("The selected account is disconnected. Reconnect it first.")
    if len(post.caption) > LIMITS["instagram_caption"]:
        raise AppError("Instagram captions are limited to 2,200 characters.")
    if post.caption.count("#") > LIMITS["instagram_hashtags"]:
        raise AppError("Instagram allows at most 30 hashtags.")
    if not post.media:
        raise AppError("Instagram posts need at least one image or video.")
    kinds = [m.get("kind") for m in post.media]
    if post.format == "carousel" and not 2 <= len(post.media) <= 10:
        raise AppError("Carousels need 2 to 10 images or videos.")
    if post.format == "reel" and kinds[0] != "video":
        raise AppError("Reels need a video.")
    if post.format == "image" and kinds[0] != "image":
        raise AppError("Image posts need an image.")
    if account.mode == "live":
        # The Instagram content publishing API accepts JPEG images and MP4/MOV video only.
        for m in post.media:
            if m.get("mime_type") not in ("image/jpeg", "video/mp4", "video/quicktime"):
                raise AppError("Instagram only accepts JPEG images and MP4/MOV videos for publishing.")
    if scheduled_at is not None and as_aware(scheduled_at) < utcnow() + MIN_LEAD:
        raise AppError("Choose a time at least 2 minutes from now.")
    return account


def request_post_approval(db: Session, post: SocialPost, scheduled_at: datetime | None, requested_by: uuid.UUID | None,
                          agent: str | None = None, group_id: uuid.UUID | None = None, reasoning: str | None = None) -> Approval:
    account = _validate_for_publish(db, post, scheduled_at)
    _supersede_pending(db, post)  # one open request per post
    post.scheduled_at = scheduled_at
    action = "schedule_post" if scheduled_at else "publish_post"
    when = as_aware(scheduled_at).strftime("%d %b %Y %H:%M UTC") if scheduled_at else "now"
    approval = approvals.request_approval(
        db, workspace_id=post.workspace_id, action_type=action, resource_type="social_post", resource_id=post.id,
        title=f"{'Schedule' if scheduled_at else 'Publish'} Instagram {post.format} on {account.display_name} ({when})",
        payload=_post_snapshot_data(post), platform="instagram", requested_by=requested_by, requested_by_agent=agent,
        group_id=group_id, ai_reasoning=reasoning,
        expected_outcome="Post goes live on Instagram" + (" at the scheduled time." if scheduled_at else " immediately."),
    )
    post.status = "in_review"
    post.approval_id = approval.id
    return approval


def _post_snapshot_data(post: SocialPost) -> dict:
    return {
        "post_id": str(post.id), "account_id": str(post.connected_account_id), "format": post.format,
        "caption": post.caption, "media": [m.get("url") for m in post.media],
        "scheduled_at": as_aware(post.scheduled_at).isoformat() if post.scheduled_at else None,
    }


def _post_snapshot(db: Session, approval: Approval) -> dict:
    return _post_snapshot_data(db.get(SocialPost, approval.resource_id))


def _post_execute(db: Session, approval: Approval, user: User) -> dict:
    post = db.get(SocialPost, approval.resource_id)
    post.approval_id = approval.id
    if approval.action_type == "schedule_post" and post.scheduled_at and as_aware(post.scheduled_at) > utcnow():
        post.status = "scheduled"
        return {"executed": True, "post_status": "scheduled"}
    post.status = "publishing"
    job = jobs.enqueue(db, "social.publish", {"post_id": post.id, "approval_id": approval.id}, workspace_id=post.workspace_id)
    return {"post_status": "publishing", "job_id": str(job.id)}


def _post_rejected(db: Session, approval: Approval) -> None:
    post = db.get(SocialPost, approval.resource_id)
    if post is not None:
        post.status = "changes_requested" if approval.status == "changes_requested" else "draft"


for _action in ("schedule_post", "publish_post"):
    register_action(_action, ActionSpec(
        permission="content:approve", execute=_post_execute, snapshot=_post_snapshot, on_rejected=_post_rejected,
        label="Schedule post" if _action == "schedule_post" else "Publish post",
    ))


@router.post("/social/posts/{post_id}/submit")
@router.post("/social/posts/{post_id}/schedule")
def submit_post(post_id: str, body: ScheduleIn, db: DB, ctx: WorkspaceContext = require("social:write")):
    """Request approval to schedule (with scheduled_at) or publish immediately (without)."""
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    if post.status in ("publishing", "published"):
        raise Conflict(f"This post is already {post.status}.")
    approval = request_post_approval(db, post, body.scheduled_at or post.scheduled_at, ctx.user.id)
    db.commit()
    return {"approval_id": str(approval.id), "status": post.status}


@router.post("/social/posts/{post_id}/publish")
def publish_now(post_id: str, db: DB, ctx: WorkspaceContext = require("social:write")):
    """Publish an approved post immediately; unapproved posts get an approval request instead."""
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    if post.status in ("approved", "scheduled") and post.approval_id:
        ctx.require("social:schedule")
        approval = db.get(Approval, post.approval_id)
        if approval is None or approval.status not in ("approved", "executed"):
            raise Conflict("This post needs a fresh approval.")
        _validate_for_publish(db, post, None)
        post.status = "publishing"
        job = jobs.enqueue(db, "social.publish", {"post_id": post.id, "approval_id": approval.id}, workspace_id=ctx.workspace_id)
        audit.record(db, "social.publish_now", ctx=ctx, resource_type="social_post", resource_id=post.id)
        db.commit()
        return {"status": post.status, "job_id": str(job.id)}
    approval = request_post_approval(db, post, None, ctx.user.id)
    db.commit()
    return {"status": post.status, "approval_id": str(approval.id), "requires_approval": True}


@router.post("/social/posts/{post_id}/cancel")
def cancel_post(post_id: str, db: DB, ctx: WorkspaceContext = require("social:write")):
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    if post.status in ("publishing", "published"):
        raise Conflict(f"This post is already {post.status}.")
    _supersede_pending(db, post)
    post.status = "cancelled"
    audit.record(db, "social.cancelled", ctx=ctx, resource_type="social_post", resource_id=post.id)
    db.commit()
    return post_out(post)


@router.post("/social/posts/{post_id}/retry")
def retry_post(post_id: str, db: DB, ctx: WorkspaceContext = require("social:schedule")):
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    if post.status != "failed" or not post.approval_id:
        raise Conflict("Only failed, previously approved posts can be retried.")
    post.status = "publishing"
    post.last_error = None
    job = jobs.enqueue(db, "social.publish", {"post_id": post.id, "approval_id": post.approval_id}, workspace_id=ctx.workspace_id)
    db.commit()
    return {"status": post.status, "job_id": str(job.id)}


@router.get("/social/posts/{post_id}/status")
def post_status(post_id: str, ctx: Ctx, db: DB):
    post = get_or_404(db, SocialPost, post_id, ctx, "Post")
    return {"status": post.status, "attempts": post.attempts, "last_error": post.last_error,
            "permalink": post.permalink, "external_id": post.external_id, "publish_log": post.publish_log,
            "published_at": as_aware(post.published_at)}


@router.get("/social/analytics")
def social_analytics(ctx: Ctx, db: DB, start: datetime | None = None, end: datetime | None = None):
    ctx.require("social:read")
    end = end or utcnow()
    start = start or end - timedelta(days=30)
    posts = db.scalars(select(SocialPost).where(
        SocialPost.workspace_id == ctx.workspace_id, SocialPost.status == "published",
        SocialPost.published_at >= start, SocialPost.published_at <= end)).all()
    measured = [p for p in posts if p.metrics]
    totals: dict[str, int] = {}
    for p in measured:
        for k, v in p.metrics.items():
            if isinstance(v, (int, float)):
                totals[k] = totals.get(k, 0) + int(v)
    engagement = sum(totals.get(k, 0) for k in ("likes", "comments", "saved", "shares"))
    top = sorted(measured, key=lambda p: sum(int(p.metrics.get(k) or 0) for k in ("likes", "comments", "saved", "shares")),
                 reverse=True)[:5]
    followers = db.scalars(select(PerformanceSnapshot).where(
        PerformanceSnapshot.workspace_id == ctx.workspace_id, PerformanceSnapshot.channel == "instagram",
        PerformanceSnapshot.date >= start.date()).order_by(PerformanceSnapshot.date)).all()
    sources = sorted({p.metrics_source for p in measured if p.metrics_source})
    return {
        "range": {"start": start, "end": end},
        "published_posts": len(posts), "posts_with_metrics": len(measured), "totals": totals,
        "engagement": engagement,
        "engagement_rate": round(engagement / totals["reach"], 4) if totals.get("reach") else None,
        "top_posts": [post_out(p) for p in top],
        "followers": [{"date": f.date, "followers": f.followers, "source": f.source} for f in followers],
        "sources": sources,
        "note": None if measured else "No engagement data yet: metrics arrive after posts are published on a live account.",
    }


# ---- publishing worker ----------------------------------------------------------------

def _log(post: SocialPost, event: str, data: dict | None = None) -> None:
    post.publish_log = [*(post.publish_log or []), {"at": utcnow().isoformat(), "event": event, **(data or {})}][-30:]


@jobs.handler("social.publish")
def _job_publish(db: Session, job: Job) -> dict:
    post = db.get(SocialPost, uuid.UUID(job.payload["post_id"]))
    if post is None or post.status == "cancelled":
        return {"skipped": True}
    if post.status == "published":
        return {"already_published": post.external_id}
    approval = db.get(Approval, uuid.UUID(job.payload["approval_id"])) if job.payload.get("approval_id") else None
    if approval is None or approval.status not in ("approved", "executed"):
        post.status = "failed"
        post.last_error = "Publishing requires an approval."
        db.commit()
        return {"refused": "no approval"}
    account = db.get(ConnectedAccount, post.connected_account_id)
    post.status = "publishing"
    post.attempts += 1
    try:
        if account.mode == "sandbox":
            result = _publish_sandbox(post, account)
        else:
            result = _publish_live(db, post, account)
    except RetryableError as exc:
        _log(post, "retryable_error", {"message": str(exc)})
        post.last_error = str(exc)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        _log(post, "error", {"message": str(exc)})
        post.status = "failed"
        post.last_error = str(exc)
        approvals.mark_execution(db, approval.id, False, {"error": str(exc)})
        db.commit()
        return {"failed": str(exc)}
    post.status = "published"
    post.external_id = result["id"]
    post.permalink = result.get("permalink")
    post.published_at = utcnow()
    post.last_error = None
    _log(post, "published", result)
    approvals.mark_execution(db, approval.id, True, {"external_id": result["id"], "permalink": result.get("permalink")})
    audit.record(db, "social.published", workspace_id=post.workspace_id, actor_type="system",
                 resource_type="social_post", resource_id=post.id, data=result)
    if post.content_asset_id:
        from app.models import Client

        client = db.scalar(select(Client).where(Client.client_workspace_id == post.workspace_id))
        if client:
            client.last_activity_at = utcnow()
    db.commit()
    return result


@jobs.on_failure("social.publish")
def _job_publish_failed(db: Session, job: Job, message: str) -> None:
    post = db.get(SocialPost, uuid.UUID(job.payload["post_id"]))
    if post is not None and post.status != "published":
        post.status = "failed"
        post.last_error = message.split("\n")[0][:1000]
        approvals.mark_execution(db, job.payload.get("approval_id"), False, {"error": post.last_error})


def _publish_sandbox(post: SocialPost, account: ConnectedAccount) -> dict:
    remaining = int((account.details or {}).get("simulate_failures", 0)) - (post.attempts - 1)
    if remaining > 0:
        raise RetryableError("Sandbox: simulated temporary platform error", delay_seconds=1)
    _log(post, "sandbox_publish", {"note": "Recorded locally; nothing was sent to Instagram."})
    return {"id": f"sandbox_{uuid.uuid4().hex[:12]}", "permalink": None, "sandbox": True}


def _publish_live(db: Session, post: SocialPost, account: ConnectedAccount) -> dict:
    client = meta.MetaClient(integrations.access_token(db, account))
    ig_user = account.details.get("ig_user_id") or account.external_id
    if not post.container_id:
        post.container_id = client.create_container(ig_user, post.format, post.caption, post.media)
        _log(post, "container_created", {"container_id": post.container_id})
        db.commit()
    status = client.container_status(post.container_id)
    _log(post, "container_status", {"status_code": status})
    if status == "IN_PROGRESS":
        db.commit()
        raise RetryableError("Instagram is still processing the media", delay_seconds=30)
    if status in ("ERROR", "EXPIRED"):
        post.container_id = None
        raise meta.MetaError(f"Instagram could not process the media ({status}).")
    return client.publish_container(ig_user, post.container_id)


def enqueue_due_posts(db: Session) -> int:
    """Scheduler tick: move due scheduled posts into the publishing queue."""
    due = db.scalars(select(SocialPost).where(SocialPost.status == "scheduled", SocialPost.scheduled_at <= utcnow())).all()
    for post in due:
        post.status = "publishing"
        jobs.enqueue(db, "social.publish", {"post_id": post.id, "approval_id": post.approval_id},
                     workspace_id=post.workspace_id, max_attempts=5)
    db.commit()
    return len(due)
