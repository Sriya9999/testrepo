"""Background worker and scheduler: `python -m app.worker`.

Runs queued jobs and, once a minute, the scheduler ticks: due Instagram posts, scheduled GEO
monitoring, scheduled reports, daily integration syncs and push notifications."""

import logging
import signal
import time

import httpx
from sqlalchemy import select

import app.main  # noqa: F401 - registers every job handler
from app.config import get_settings
from app.db import SessionLocal, utcnow
from app.models import Notification, PushDevice
from app.services import jobs

log = logging.getLogger("marketingos.worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def send_push_notifications() -> int:
    """Deliver new notifications to registered mobile devices through Expo's push service."""
    with SessionLocal() as db:
        pending = db.scalars(select(Notification).where(Notification.pushed_at.is_(None)).limit(100)).all()
        messages = []
        for n in pending:
            for d in db.scalars(select(PushDevice).where(PushDevice.user_id == n.user_id)):
                messages.append({"to": d.token, "title": n.title, "body": n.body[:180], "data": n.data})
            n.pushed_at = utcnow()
        if messages:
            try:
                httpx.post("https://exp.host/--/api/v2/push/send", json=messages, timeout=15)
            except httpx.HTTPError as exc:
                log.warning("push delivery failed: %s", exc)
        db.commit()
        return len(messages)


def scheduler_tick() -> None:
    from app.api.analytics import enqueue_scheduled_reports
    from app.api.geo import enqueue_scheduled_monitoring
    from app.api.social import enqueue_due_posts
    from app.jobs.sync import enqueue_daily_syncs

    for name, fn in (("posts", enqueue_due_posts), ("geo", enqueue_scheduled_monitoring), ("reports", enqueue_scheduled_reports),
                     ("syncs", enqueue_daily_syncs)):
        try:
            with SessionLocal() as db:
                count = fn(db)
            if count:
                log.info("scheduler: queued %s %s job(s)", count, name)
        except Exception:  # noqa: BLE001 - one failing tick must not stop the others
            log.exception("scheduler step %s failed", name)
    try:
        send_push_notifications()
    except Exception:  # noqa: BLE001
        log.exception("push step failed")


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    poll = get_settings().worker_poll_seconds
    last_tick = 0.0
    log.info("worker %s started", jobs.WORKER_ID)
    while _running:
        if time.monotonic() - last_tick >= 60:
            scheduler_tick()
            last_tick = time.monotonic()
        ran = jobs.run_pending(max_jobs=10)
        if not ran:
            time.sleep(poll)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
