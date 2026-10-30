import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from app.deps import DB, Ctx, WorkspaceContext, get_or_404, require
from app.errors import NotFound
from app.models import Brand, MediaAsset
from app.services import audit, storage

router = APIRouter(tags=["brands"])
public_router = APIRouter()

HEX = r"^#[0-9A-Fa-f]{6}$"


class Product(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = None
    description: str = ""
    website_url: str | None = None
    colors: list[str] = []
    fonts: list[str] = []
    target_customers: str = ""
    products: list[Product] = []
    voice: str = ""
    competitor_references: list[str] = []
    prohibited_claims: list[str] = []
    approved_ctas: list[str] = []
    locations: list[str] = []
    languages: list[str] = ["en"]
    is_default: bool = False

    @field_validator("colors")
    @classmethod
    def _colors(cls, v: list[str]) -> list[str]:
        import re

        for c in v:
            if not re.match(HEX, c):
                raise ValueError(f"'{c}' is not a #RRGGBB colour")
        return v


class BrandPatch(BrandIn):
    name: str | None = None  # type: ignore[assignment]
    is_default: bool | None = None  # type: ignore[assignment]


def brand_out(b: Brand) -> dict:
    return {
        "id": str(b.id), "name": b.name, "industry": b.industry, "description": b.description,
        "website_url": b.website_url, "logo_url": b.logo_url, "colors": b.colors, "fonts": b.fonts,
        "target_customers": b.target_customers, "products": b.products, "voice": b.voice,
        "competitor_references": b.competitor_references, "prohibited_claims": b.prohibited_claims,
        "approved_ctas": b.approved_ctas, "locations": b.locations, "languages": b.languages,
        "is_default": b.is_default, "updated_at": b.updated_at,
    }


def brand_context(b: Brand | None) -> dict:
    """The brand memory handed to the AI before every generation."""
    if b is None:
        return {}
    data = brand_out(b)
    for key in ("id", "updated_at", "is_default", "logo_url"):
        data.pop(key, None)
    return data


def _set_default(db, ctx, brand: Brand) -> None:
    db.execute(update(Brand).where(Brand.workspace_id == ctx.workspace_id, Brand.id != brand.id).values(is_default=False))
    brand.is_default = True


@router.post("/brands", status_code=201)
def create_brand(body: BrandIn, db: DB, ctx: WorkspaceContext = require("brand:write")):
    data = body.model_dump()
    data["products"] = [p for p in data["products"]]
    brand = Brand(workspace_id=ctx.workspace_id, **data)
    db.add(brand)
    db.flush()
    has_other = db.scalar(select(Brand).where(Brand.workspace_id == ctx.workspace_id, Brand.id != brand.id))
    if body.is_default or not has_other:
        _set_default(db, ctx, brand)
    audit.record(db, "brand.created", ctx=ctx, resource_type="brand", resource_id=brand.id)
    db.commit()
    return brand_out(brand)


@router.get("/brands")
def list_brands(ctx: Ctx, db: DB):
    ctx.require("brand:read")
    rows = db.scalars(select(Brand).where(Brand.workspace_id == ctx.workspace_id).order_by(Brand.is_default.desc(), Brand.name))
    return [brand_out(b) for b in rows]


@router.get("/brands/{brand_id}")
def get_brand(brand_id: str, ctx: Ctx, db: DB):
    ctx.require("brand:read")
    return brand_out(get_or_404(db, Brand, brand_id, ctx, "Brand"))


@router.patch("/brands/{brand_id}")
def update_brand(brand_id: str, body: BrandPatch, db: DB, ctx: WorkspaceContext = require("brand:write")):
    brand = get_or_404(db, Brand, brand_id, ctx, "Brand")
    changes = body.model_dump(exclude_unset=True)
    make_default = changes.pop("is_default", None)
    for key, value in changes.items():
        if value is not None:
            setattr(brand, key, value)
    if make_default:
        _set_default(db, ctx, brand)
    audit.record(db, "brand.updated", ctx=ctx, resource_type="brand", resource_id=brand.id, data={"fields": list(changes)})
    db.commit()
    return brand_out(brand)


def media_out(m: MediaAsset) -> dict:
    return {
        "id": str(m.id), "url": storage.public_url(m.storage_key), "kind": m.kind, "mime_type": m.mime_type,
        "filename": m.filename, "size_bytes": m.size_bytes, "width": m.width, "height": m.height,
        "source": m.source, "purpose": m.purpose, "prompt": m.prompt,
        "brand_id": str(m.brand_id) if m.brand_id else None, "created_at": m.created_at,
    }


async def _store_upload(db, ctx, file: UploadFile, purpose: str, brand_id: uuid.UUID | None) -> MediaAsset:
    data = await file.read()
    mime = (file.content_type or "").split(";")[0].strip()
    ext = storage.validate_upload(data, mime)
    key = storage.save_bytes(data, ext, prefix=f"ws/{ctx.workspace_id}")
    media = MediaAsset(
        workspace_id=ctx.workspace_id, brand_id=brand_id, purpose=purpose,
        kind="video" if mime.startswith("video/") else ("document" if mime in ("application/pdf", "text/csv") else "image"),
        storage_key=key, filename=(file.filename or "")[:255], mime_type=mime, size_bytes=len(data),
        source="upload", created_by=ctx.user.id,
    )
    db.add(media)
    db.flush()
    return media


@router.post("/brands/{brand_id}/assets", status_code=201)
async def upload_brand_asset(
    brand_id: str, db: DB, file: UploadFile = File(...),
    purpose: Literal["brand_logo", "brand_asset"] = Form("brand_asset"),
    ctx: WorkspaceContext = require("brand:write"),
):
    brand = get_or_404(db, Brand, brand_id, ctx, "Brand")
    media = await _store_upload(db, ctx, file, purpose, brand.id)
    if purpose == "brand_logo":
        brand.logo_url = storage.public_url(media.storage_key)
    audit.record(db, "brand.asset_uploaded", ctx=ctx, resource_type="media", resource_id=media.id)
    db.commit()
    return media_out(media)


@router.get("/brands/{brand_id}/assets")
def list_brand_assets(brand_id: str, ctx: Ctx, db: DB):
    brand = get_or_404(db, Brand, brand_id, ctx, "Brand")
    rows = db.scalars(select(MediaAsset).where(MediaAsset.brand_id == brand.id).order_by(MediaAsset.created_at.desc()))
    return [media_out(m) for m in rows]


@router.post("/media", status_code=201)
async def upload_media(db: DB, file: UploadFile = File(...), ctx: WorkspaceContext = require("media:upload")):
    media = await _store_upload(db, ctx, file, "creative", None)
    db.commit()
    return media_out(media)


@router.get("/media")
def list_media(ctx: Ctx, db: DB, kind: str | None = None, limit: int = 60):
    stmt = select(MediaAsset).where(MediaAsset.workspace_id == ctx.workspace_id)
    if kind:
        stmt = stmt.where(MediaAsset.kind == kind)
    return [media_out(m) for m in db.scalars(stmt.order_by(MediaAsset.created_at.desc()).limit(min(limit, 200)))]


@public_router.get("/media/{key:path}", include_in_schema=False)
def serve_media(key: str, db: DB):
    media = db.scalar(select(MediaAsset).where(MediaAsset.storage_key == key))
    if media is None:
        raise NotFound("File not found")
    try:
        data = storage.read_bytes(key)
    except FileNotFoundError as exc:
        raise NotFound("File not found") from exc
    headers = {"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}
    if media.mime_type == "image/svg+xml":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return Response(content=data, media_type=media.mime_type, headers=headers)
