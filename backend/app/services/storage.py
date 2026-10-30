"""File storage with upload validation.

Files are written under STORAGE_DIR with random keys and served at /media/<key>. Keys are
unguessable because platforms such as Instagram must fetch media from a public URL. For
production put STORAGE_DIR on an S3-compatible bucket mount or replace save/read here.
"""

import secrets
from pathlib import Path

from app.config import get_settings
from app.errors import AppError

ALLOWED_TYPES = {
    "image/png": (".png", [b"\x89PNG\r\n\x1a\n"]),
    "image/jpeg": (".jpg", [b"\xff\xd8\xff"]),
    "image/webp": (".webp", [b"RIFF"]),
    "image/gif": (".gif", [b"GIF87a", b"GIF89a"]),
    "image/svg+xml": (".svg", [b"<svg", b"<?xml"]),
    "video/mp4": (".mp4", []),  # ftyp box is checked below
    "video/quicktime": (".mov", []),
    "application/pdf": (".pdf", [b"%PDF"]),
    "text/csv": (".csv", []),
}


def _root() -> Path:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_upload(data: bytes, mime_type: str) -> str:
    """Return the file extension, or raise if the file is not an allowed, well-formed type."""
    settings = get_settings()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise AppError("File is empty")
    if mime_type not in ALLOWED_TYPES:
        raise AppError(f"Unsupported file type {mime_type}")
    ext, signatures = ALLOWED_TYPES[mime_type]
    head = data[:64].lstrip()
    if signatures and not any(head.startswith(sig) for sig in signatures):
        raise AppError("File contents do not match its declared type")
    if mime_type.startswith("video/") and b"ftyp" not in data[:32]:
        raise AppError("File contents do not match its declared type")
    if mime_type == "image/svg+xml":
        lowered = data.lower()
        if b"<script" in lowered or b"javascript:" in lowered or _has_event_handler(lowered):
            raise AppError("SVG files with scripts or event handlers are not allowed")
    return ext


def _has_event_handler(svg: bytes) -> bool:
    import re

    return re.search(rb"\son[a-z]+\s*=", svg) is not None


def save_bytes(data: bytes, ext: str, prefix: str = "media") -> str:
    key = f"{prefix}/{secrets.token_urlsafe(18)}{ext}"
    path = _root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def read_bytes(key: str) -> bytes:
    path = (_root() / key).resolve()
    if _root() not in path.parents or not path.is_file():
        raise FileNotFoundError(key)
    return path.read_bytes()


def public_url(key: str) -> str:
    return f"{get_settings().public_api_url.rstrip('/')}/media/{key}"
