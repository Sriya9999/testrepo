import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Uuid, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONType, list: JSONType, uuid.UUID: Uuid}


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TenantMixin:
    """Every business record belongs to exactly one workspace (the tenant)."""

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )


def _make_engine(url: str):
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - driver hook
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure_engine(url: str) -> None:
    """Rebind the session factory (used by tests)."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def as_aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive datetimes read back from it as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
