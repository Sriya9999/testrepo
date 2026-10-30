"""A Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED).

Handlers are registered with @handler("type") and receive (db, job). A handler that raises
RetryableError is retried with exponential backoff up to job.max_attempts; any other
exception fails the job immediately. Swap for Celery/Temporal when volume demands it:
only enqueue() and the worker loop know about this table.
"""

import logging
import socket
import traceback
import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, as_aware, is_postgres, utcnow
from app.models import Job

log = logging.getLogger("marketingos.jobs")

HANDLERS: dict[str, Callable[[Session, Job], dict | None]] = {}
WORKER_ID = f"{socket.gethostname()}:{uuid.uuid4().hex[:6]}"
STALE_LOCK = timedelta(minutes=15)


class RetryableError(Exception):
    """A temporary failure (rate limit, timeout, platform still processing)."""

    def __init__(self, message: str, delay_seconds: int | None = None):
        super().__init__(message)
        self.delay_seconds = delay_seconds


def handler(job_type: str):
    def register(fn):
        HANDLERS[job_type] = fn
        return fn

    return register


def enqueue(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    *,
    workspace_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    delay_seconds: int = 0,
    max_attempts: int | None = None,
) -> Job:
    job = Job(
        type=job_type,
        payload={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in (payload or {}).items()},
        workspace_id=workspace_id,
        created_by=created_by,
        run_after=utcnow() + timedelta(seconds=delay_seconds),
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def _claim(db: Session) -> Job | None:
    now = utcnow()
    stmt = (
        select(Job)
        .where(
            or_(
                (Job.status == "queued") & (Job.run_after <= now),
                (Job.status == "running") & (Job.locked_at < now - STALE_LOCK),
            )
        )
        .order_by(Job.run_after)
        .limit(1)
    )
    if is_postgres(db):
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = "running"
    job.locked_at = now
    job.locked_by = WORKER_ID
    job.attempts += 1
    db.commit()
    return job


def run_job(job_id: uuid.UUID) -> str:
    """Execute one claimed job in its own session. Returns the final status."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        fn = HANDLERS.get(job.type)
        try:
            if fn is None:
                raise RuntimeError(f"No handler registered for job type '{job.type}'")
            result = fn(db, job) or {}
            job = db.get(Job, job_id)
            job.status = "succeeded"
            job.result = result
            job.error = None
            job.finished_at = utcnow()
            db.commit()
        except RetryableError as exc:
            db.rollback()
            job = db.get(Job, job_id)
            job.error = str(exc)
            if job.attempts < job.max_attempts:
                delay = exc.delay_seconds or min(30 * 2 ** (job.attempts - 1), 3600)
                job.status = "queued"
                job.run_after = utcnow() + timedelta(seconds=delay)
                job.locked_at = None
            else:
                job.status = "failed"
                job.finished_at = utcnow()
                _on_final_failure(db, job, str(exc))
            db.commit()
        except Exception as exc:  # noqa: BLE001 - we record every failure on the job
            db.rollback()
            log.exception("job %s (%s) failed", job_id, job.type)
            job = db.get(Job, job_id)
            job.status = "failed"
            job.error = f"{exc}\n{traceback.format_exc(limit=3)}"[:4000]
            job.finished_at = utcnow()
            _on_final_failure(db, job, str(exc))
            db.commit()
        return job.status


FAILURE_HOOKS: dict[str, Callable[[Session, Job, str], None]] = {}


def on_failure(job_type: str):
    """Register a hook that marks the domain object failed when its job gives up."""

    def register(fn):
        FAILURE_HOOKS[job_type] = fn
        return fn

    return register


def _on_final_failure(db: Session, job: Job, message: str) -> None:
    hook = FAILURE_HOOKS.get(job.type)
    if hook:
        try:
            hook(db, job, message)
        except Exception:  # noqa: BLE001
            log.exception("failure hook for %s raised", job.type)


def run_pending(max_jobs: int = 100, include_delayed: bool = False) -> int:
    """Drain the queue synchronously (used by tests and the dev 'run now' endpoint)."""
    count = 0
    for _ in range(max_jobs):
        with SessionLocal() as db:
            if include_delayed:
                pending = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1))
                if pending is not None:
                    pending.run_after = utcnow()
                    db.commit()
            job = _claim(db)
            if job is None:
                break
            job_id = job.id
        run_job(job_id)
        count += 1
    return count


def job_status(job: Job) -> dict:
    return {
        "id": str(job.id),
        "type": job.type,
        "status": job.status,
        "attempts": job.attempts,
        "result": job.result,
        "error": (job.error or "").split("\n")[0] or None,
        "created_at": as_aware(job.created_at),
        "finished_at": as_aware(job.finished_at),
    }
