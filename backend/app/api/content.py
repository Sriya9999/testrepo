import json
import uuid
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.brands import brand_context, media_out
from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.engines import content_formats
from app.errors import AppError, Conflict, NotFound
from app.models import Approval, Brand, ContentAsset, ContentVersion, Job, MediaAsset, User
from app.providers.ai import get_ai
from app.services import approvals, audit, credits, jobs, storage
from app.services.accounts import default_brand
from app.services.approvals import ActionSpec, register_action

router = APIRouter(tags=["content"])


class GenerateIn(BaseModel):
    brand_id: uuid.UUID | None = None
    platform: str
    format: str
    title: str | None = Field(default=None, max_length=300)
    objective: str = "engagement"
    topic: str = ""
    product: str = ""
    audience: str = ""
    industry: str = ""
    language: str = "en"
    tone: str = ""
    keywords: list[str] = []
    cta: str = ""
    location: str | None = None
    question: str | None = None
    dimensions: Literal["square", "portrait", "story", "landscape"] = "square"
    number_of_slides: int = Field(default=5, ge=2, le=10)
    variations: int = Field(default=1, ge=1, le=5)


class ImageIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    brand_id: uuid.UUID | None = None
    content_id: uuid.UUID | None = None
    dimensions: Literal["square", "portrait", "story", "landscape"] = "square"
    count: int = Field(default=1, ge=1, le=4)


class VariationsIn(BaseModel):
    content_id: uuid.UUID
    count: int = Field(default=2, ge=1, le=5)


class EditIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    body: dict | None = None
    note: str | None = None


class SectionIn(BaseModel):
    section: str


class DecisionNote(BaseModel):
    note: str | None = None


def _brand(db: Session, ctx, brand_id) -> Brand | None:
    if brand_id:
        return get_or_404(db, Brand, brand_id, ctx, "Brand")
    return default_brand(db, ctx.workspace_id)


def content_out(db: Session, a: ContentAsset, with_versions: bool = False) -> dict:
    out = {
        "id": str(a.id), "title": a.title, "platform": a.platform, "format": a.format, "objective": a.objective,
        "language": a.language, "status": a.status, "current_version": a.current_version, "body": a.body,
        "brief": a.brief, "quality": a.quality, "generation_status": a.generation_status,
        "generation_error": a.generation_error, "provider": a.provider,
        "brand_id": str(a.brand_id) if a.brand_id else None, "created_at": a.created_at, "updated_at": a.updated_at,
    }
    if with_versions:
        out["versions"] = [
            {"version": v.version, "source": v.source, "label": v.label, "note": v.note, "created_at": v.created_at,
             "body": v.body}
            for v in db.scalars(select(ContentVersion).where(ContentVersion.content_asset_id == a.id).order_by(ContentVersion.version))
        ]
        pending = db.scalar(select(Approval).where(Approval.resource_id == a.id, Approval.status == "pending"))
        out["pending_approval_id"] = str(pending.id) if pending else None
    return out


def _next_version(db: Session, asset_id: uuid.UUID) -> int:
    return (db.scalar(select(func.max(ContentVersion.version)).where(ContentVersion.content_asset_id == asset_id)) or 0) + 1


def _invalidate_approval(db: Session, asset: ContentAsset) -> None:
    """Editing approved or in-review content sends it back to draft."""
    if asset.status in ("approved", "in_review"):
        asset.status = "draft"
    for a in db.scalars(select(Approval).where(Approval.resource_id == asset.id, Approval.status == "pending")):
        a.status = "superseded"


@router.get("/content/formats")
def formats(ctx: Ctx, db: DB):
    return {
        "formats": {
            platform: [{"format": f, "label": content_formats.FORMAT_LABELS.get(f, f),
                        "credits": credits.cost_of(db, op), "sections": content_formats.SECTIONS.get(f, [])}
                       for f, op in fmts.items()]
            for platform, fmts in content_formats.FORMATS.items()
        },
        "dimensions": content_formats.DIMENSIONS,
        "image_credits": credits.cost_of(db, "image_generation"),
        "variation_credits": credits.cost_of(db, "content_variation"),
        "provider": get_ai().name,
    }


@router.post("/content/generate", status_code=202)
def generate(body: GenerateIn, db: DB, ctx: WorkspaceContext = require("content:write")):
    try:
        op = content_formats.billing_operation(body.platform, body.format)
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    items = [(op, 1)] + ([("content_variation", body.variations - 1)] if body.variations > 1 else [])
    estimate = credits.ensure_affordable(db, ctx.workspace_id, items)
    brand = _brand(db, ctx, body.brand_id)
    brief = body.model_dump(mode="json", exclude={"brand_id", "title", "variations"})
    asset = ContentAsset(
        workspace_id=ctx.workspace_id, brand_id=brand.id if brand else None, platform=body.platform,
        format=body.format, objective=body.objective, language=body.language, brief=brief,
        title=body.title or f"{content_formats.FORMAT_LABELS.get(body.format, body.format)}: {body.topic or body.product or 'untitled'}"[:300],
        generation_status="pending", created_by=ctx.user.id, current_version=0,
    )
    db.add(asset)
    db.flush()
    job = jobs.enqueue(db, "content.generate", {"content_id": asset.id, "variations": body.variations},
                       workspace_id=ctx.workspace_id, created_by=ctx.user.id)
    db.commit()
    return {"job_id": str(job.id), "status": "processing", "content_id": str(asset.id),
            "estimated_outputs": body.variations, "estimated_credits": estimate}


def generate_into(db: Session, asset: ContentAsset, variations: int, actor_id: uuid.UUID | None, reference: str) -> int:
    """Generate the main draft (+ variations) for an asset and charge for them. Shared by the
    Content Studio job and the Content Agent."""
    brand = db.get(Brand, asset.brand_id) if asset.brand_id else None
    ai = get_ai()
    bctx = brand_context(brand)
    outputs = [ai.write_content(asset.platform, asset.format, asset.brief, bctx, variation=i) for i in range(variations)]
    for i, out in enumerate(outputs):
        db.add(ContentVersion(
            content_asset_id=asset.id, version=i + 1, body=out, source="ai" if i == 0 else "variation",
            label="Original" if i == 0 else f"Variation {i}", created_by=actor_id,
        ))
    asset.body = outputs[0]
    asset.current_version = 1
    asset.quality = content_formats.check(asset.platform, asset.format, outputs[0], brand)
    asset.generation_status = "ready"
    asset.generation_error = None
    asset.provider = ai.name
    op = content_formats.billing_operation(asset.platform, asset.format)
    used = credits.charge(db, asset.workspace_id, op, 1, reference=reference, actor_id=actor_id,
                          description=f"Generated {asset.platform} {asset.format}")
    if variations > 1:
        used += credits.charge(db, asset.workspace_id, "content_variation", variations - 1, reference=reference, actor_id=actor_id)
    return used


@jobs.handler("content.generate")
def _job_generate(db: Session, job: Job) -> dict:
    asset = db.get(ContentAsset, uuid.UUID(job.payload["content_id"]))
    if asset is None:
        return {"skipped": "content deleted"}
    used = generate_into(db, asset, int(job.payload.get("variations", 1)), job.created_by, str(job.id))
    db.commit()
    return {"content_id": str(asset.id), "credits_used": used}


@jobs.on_failure("content.generate")
def _job_generate_failed(db: Session, job: Job, message: str) -> None:
    asset = db.get(ContentAsset, uuid.UUID(job.payload["content_id"]))
    if asset is not None:
        asset.generation_status = "failed"
        asset.generation_error = message.split("\n")[0][:500]


@router.post("/content/images/generate", status_code=202)
def generate_image(body: ImageIn, db: DB, ctx: WorkspaceContext = require("content:write")):
    estimate = credits.ensure_affordable(db, ctx.workspace_id, [("image_generation", body.count)])
    brand = _brand(db, ctx, body.brand_id)
    if body.content_id:
        get_or_404(db, ContentAsset, body.content_id, ctx, "Content")
    job = jobs.enqueue(db, "content.image", {
        "prompt": body.prompt, "brand_id": brand.id if brand else None, "content_id": body.content_id,
        "dimensions": body.dimensions, "count": body.count,
    }, workspace_id=ctx.workspace_id, created_by=ctx.user.id)
    db.commit()
    return {"job_id": str(job.id), "status": "processing", "estimated_outputs": body.count, "estimated_credits": estimate}


def create_images(db: Session, workspace_id: uuid.UUID, prompt: str, brand: Brand | None, dimensions: str,
                  count: int, actor_id: uuid.UUID | None, reference: str) -> list[MediaAsset]:
    width, height = content_formats.DIMENSIONS[dimensions]
    ai = get_ai()
    created = []
    for _ in range(count):
        data, mime, source = ai.image(prompt, width, height, brand_context(brand))
        ext = storage.ALLOWED_TYPES[mime][0]
        key = storage.save_bytes(data, ext, prefix=f"ws/{workspace_id}")
        media = MediaAsset(
            workspace_id=workspace_id, brand_id=brand.id if brand else None, purpose="creative", kind="image",
            storage_key=key, filename=f"generated{ext}", mime_type=mime, size_bytes=len(data), width=width,
            height=height, source=source, prompt=prompt, created_by=actor_id,
        )
        db.add(media)
        created.append(media)
    db.flush()
    credits.charge(db, workspace_id, "image_generation", count, reference=reference, actor_id=actor_id,
                   description="Generated image" if count == 1 else f"Generated {count} images")
    return created


@jobs.handler("content.image")
def _job_image(db: Session, job: Job) -> dict:
    p = job.payload
    brand = db.get(Brand, uuid.UUID(p["brand_id"])) if p.get("brand_id") else None
    media = create_images(db, job.workspace_id, p["prompt"], brand, p["dimensions"], int(p["count"]), job.created_by, str(job.id))
    if p.get("content_id"):
        asset = db.get(ContentAsset, uuid.UUID(p["content_id"]))
        if asset is not None:
            body = dict(asset.body or {})
            body["media"] = list(body.get("media") or []) + [
                {"media_asset_id": str(m.id), "url": storage.public_url(m.storage_key), "kind": "image"} for m in media]
            asset.body = body
    db.commit()
    return {"media": [media_out(m) for m in media]}


@router.post("/content/variations", status_code=202)
def variations(body: VariationsIn, db: DB, ctx: WorkspaceContext = require("content:write")):
    asset = get_or_404(db, ContentAsset, body.content_id, ctx, "Content")
    estimate = credits.ensure_affordable(db, ctx.workspace_id, [("content_variation", body.count)])
    job = jobs.enqueue(db, "content.variations", {"content_id": asset.id, "count": body.count},
                       workspace_id=ctx.workspace_id, created_by=ctx.user.id)
    db.commit()
    return {"job_id": str(job.id), "status": "processing", "estimated_outputs": body.count, "estimated_credits": estimate}


@jobs.handler("content.variations")
def _job_variations(db: Session, job: Job) -> dict:
    asset = db.get(ContentAsset, uuid.UUID(job.payload["content_id"]))
    brand = db.get(Brand, asset.brand_id) if asset.brand_id else None
    ai = get_ai()
    start = _next_version(db, asset.id)
    existing = db.scalar(select(func.count()).select_from(ContentVersion).where(ContentVersion.content_asset_id == asset.id)) or 0
    count = int(job.payload["count"])
    for i in range(count):
        out = ai.write_content(asset.platform, asset.format, asset.brief, brand_context(brand), variation=existing + i)
        db.add(ContentVersion(content_asset_id=asset.id, version=start + i, body=out, source="variation",
                              label=f"Variation {start + i - 1}", created_by=job.created_by))
    credits.charge(db, asset.workspace_id, "content_variation", count, reference=str(job.id), actor_id=job.created_by)
    db.commit()
    return {"content_id": str(asset.id), "versions_added": count}


@router.get("/content")
def list_content(ctx: Ctx, db: DB, platform: str | None = None, status: str | None = None, format: str | None = None,
                 q: str | None = None, limit: int = 100):
    ctx.require("content:read")
    stmt = select(ContentAsset).where(ContentAsset.workspace_id == ctx.workspace_id)
    if platform:
        stmt = stmt.where(ContentAsset.platform == platform)
    if status:
        stmt = stmt.where(ContentAsset.status == status)
    if format:
        stmt = stmt.where(ContentAsset.format == format)
    if q:
        stmt = stmt.where(ContentAsset.title.ilike(f"%{q}%"))
    rows = db.scalars(stmt.order_by(ContentAsset.updated_at.desc()).limit(min(limit, 300)))
    return [content_out(db, a) for a in rows]


@router.get("/content/{content_id}")
def get_content(content_id: str, ctx: Ctx, db: DB):
    ctx.require("content:read")
    return content_out(db, get_or_404(db, ContentAsset, content_id, ctx, "Content"), with_versions=True)


@router.patch("/content/{content_id}")
def edit_content(content_id: str, body: EditIn, db: DB, ctx: WorkspaceContext = require("content:write")):
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    if asset.generation_status == "pending":
        raise Conflict("This content is still being generated.")
    if body.title is not None:
        asset.title = body.title
    if body.body is not None and body.body != asset.body:
        version = _next_version(db, asset.id)
        db.add(ContentVersion(content_asset_id=asset.id, version=version, body=body.body, source="user",
                              note=body.note, created_by=ctx.user.id))
        asset.body = body.body
        asset.current_version = version
        brand = db.get(Brand, asset.brand_id) if asset.brand_id else None
        asset.quality = content_formats.check(asset.platform, asset.format, body.body, brand)
        _invalidate_approval(db, asset)
    db.commit()
    return content_out(db, asset, with_versions=True)


@router.post("/content/{content_id}/versions/{version}/select")
def select_version(content_id: str, version: int, db: DB, ctx: WorkspaceContext = require("content:write")):
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    v = db.scalar(select(ContentVersion).where(ContentVersion.content_asset_id == asset.id, ContentVersion.version == version))
    if v is None:
        raise NotFound("Version not found")
    asset.body = v.body
    asset.current_version = v.version
    brand = db.get(Brand, asset.brand_id) if asset.brand_id else None
    asset.quality = content_formats.check(asset.platform, asset.format, v.body, brand)
    _invalidate_approval(db, asset)
    db.commit()
    return content_out(db, asset, with_versions=True)


@router.post("/content/{content_id}/regenerate")
def regenerate_section(content_id: str, body: SectionIn, db: DB, ctx: WorkspaceContext = require("content:write")):
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    if body.section not in content_formats.SECTIONS.get(asset.format, []):
        raise AppError(f"'{body.section}' cannot be regenerated for a {asset.format}.")
    credits.ensure_affordable(db, ctx.workspace_id, [("section_regeneration", 1)])
    brand = db.get(Brand, asset.brand_id) if asset.brand_id else None
    seed = _next_version(db, asset.id) + 7
    value = get_ai().regenerate_section(asset.platform, asset.format, asset.body, body.section, asset.brief, brand_context(brand), seed)
    new_body = {**asset.body, body.section: value}
    version = _next_version(db, asset.id)
    db.add(ContentVersion(content_asset_id=asset.id, version=version, body=new_body, source="ai",
                          label=f"Regenerated {body.section}", created_by=ctx.user.id))
    asset.body = new_body
    asset.current_version = version
    asset.quality = content_formats.check(asset.platform, asset.format, new_body, brand)
    _invalidate_approval(db, asset)
    credits.charge(db, ctx.workspace_id, "section_regeneration", reference=str(asset.id), actor_id=ctx.user.id)
    db.commit()
    return content_out(db, asset, with_versions=True)


@router.post("/content/{content_id}/duplicate", status_code=201)
def duplicate(content_id: str, db: DB, ctx: WorkspaceContext = require("content:write")):
    src = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    copy = ContentAsset(
        workspace_id=ctx.workspace_id, brand_id=src.brand_id, title=f"{src.title} (copy)"[:300], platform=src.platform,
        format=src.format, objective=src.objective, language=src.language, body=src.body, brief=src.brief,
        quality=src.quality, created_by=ctx.user.id, current_version=1, provider=src.provider,
    )
    db.add(copy)
    db.flush()
    db.add(ContentVersion(content_asset_id=copy.id, version=1, body=src.body, source="user", label="Duplicated",
                          created_by=ctx.user.id))
    db.commit()
    return content_out(db, copy, with_versions=True)


@router.delete("/content/{content_id}", status_code=204)
def delete_content(content_id: str, db: DB, ctx: WorkspaceContext = require("content:write")):
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    if asset.status == "approved" and not ctx.can("content:approve"):
        raise AppError("Approved content can only be deleted by someone who can approve content.")
    audit.record(db, "content.deleted", ctx=ctx, resource_type="content", resource_id=asset.id, data={"title": asset.title})
    db.delete(asset)
    db.commit()


def _content_snapshot(db: Session, approval: Approval) -> dict:
    asset = db.get(ContentAsset, approval.resource_id)
    return {"content_id": str(asset.id), "version": asset.current_version, "body": asset.body}


def _content_execute(db: Session, approval: Approval, user: User) -> dict:
    asset = db.get(ContentAsset, approval.resource_id)
    asset.status = "approved"
    return {"executed": True, "content_status": "approved"}


def _content_rejected(db: Session, approval: Approval) -> None:
    asset = db.get(ContentAsset, approval.resource_id)
    if asset is not None:
        asset.status = "rejected" if approval.status == "rejected" else "changes_requested"


register_action("approve_content", ActionSpec(
    permission="content:approve", execute=_content_execute, snapshot=_content_snapshot,
    on_rejected=_content_rejected, label="Approve content",
))


def submit_content(db: Session, asset: ContentAsset, requested_by: uuid.UUID | None, agent: str | None = None,
                   group_id: uuid.UUID | None = None, reasoning: str | None = None) -> Approval:
    if asset.generation_status != "ready":
        raise Conflict("Content is not ready yet.")
    if asset.quality and not asset.quality.get("ok", True):
        raise AppError("Fix the blocking issues before submitting.", code="quality_check_failed", details=asset.quality)
    payload = {"content_id": str(asset.id), "version": asset.current_version, "body": asset.body}
    approval = approvals.request_approval(
        db, workspace_id=asset.workspace_id, action_type="approve_content", resource_type="content",
        resource_id=asset.id, title=f"Content: {asset.title}", payload=payload, platform=asset.platform,
        requested_by=requested_by, requested_by_agent=agent, group_id=group_id,
        ai_reasoning=reasoning or ("Generated with the brand profile and checked against platform rules."
                                   if asset.provider else None),
        expected_outcome=f"Approved {content_formats.FORMAT_LABELS.get(asset.format, asset.format).lower()} ready to schedule.",
    )
    asset.status = "in_review"
    return approval


@router.post("/content/{content_id}/submit")
def submit(content_id: str, db: DB, ctx: WorkspaceContext = require("content:write")):
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    approval = submit_content(db, asset, ctx.user.id)
    db.commit()
    return {"approval_id": str(approval.id), "status": asset.status}


@router.post("/content/{content_id}/approve")
def approve(content_id: str, body: DecisionNote, db: DB, ctx: WorkspaceContext = require("content:approve")):
    """Approve content directly (the reviewer's shortcut for the Approval Center)."""
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    approval = db.scalar(select(Approval).where(Approval.resource_id == asset.id, Approval.action_type == "approve_content",
                                                Approval.status == "pending"))
    if approval is None:
        approval = submit_content(db, asset, ctx.user.id)
        db.flush()
    approvals.decide(db, ctx, approval, "approve", body.note)
    db.commit()
    return content_out(db, asset, with_versions=True)


@router.post("/content/{content_id}/export")
def export(content_id: str, ctx: Ctx, db: DB, format: Literal["json", "md", "txt"] = "md"):
    ctx.require("content:read")
    asset = get_or_404(db, ContentAsset, content_id, ctx, "Content")
    if format == "json":
        data, mime = json.dumps({"title": asset.title, **asset.body}, indent=2, ensure_ascii=False), "application/json"
    else:
        data, mime = to_markdown(asset.title, asset.body), "text/markdown" if format == "md" else "text/plain"
    filename = f"{asset.title[:60].replace(' ', '_') or 'content'}.{format}"
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def to_markdown(title: str, body) -> str:
    lines = [f"# {title}", ""]

    def walk(value, depth=2, label=None):
        if label:
            lines.append(f"{'#' * min(depth, 6)} {label.replace('_', ' ').capitalize()}")
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, depth + 1, k)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    lines.append("- " + " | ".join(f"**{k}**: {v}" for k, v in item.items() if v not in (None, "")))
                else:
                    lines.append(f"- {item}")
            lines.append("")
        elif value not in (None, ""):
            lines.extend([str(value), ""])

    for key, value in (body or {}).items():
        walk(value, 2, key)
    return "\n".join(lines)

