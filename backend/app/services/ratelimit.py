"""Fixed-window rate limiting. Uses Redis when REDIS_URL is set (shared across API replicas),
otherwise an in-process window, which is fine for a single instance and for tests."""

import threading
import time

from fastapi import Request

from app.config import get_settings
from app.deps import client_ip
from app.errors import TooManyRequests

_lock = threading.Lock()
_windows: dict[str, tuple[int, int]] = {}
_redis = None


def _redis_client():
    global _redis
    url = get_settings().redis_url
    if not url:
        return None
    if _redis is None:
        import redis

        _redis = redis.Redis.from_url(url)
    return _redis


def hit(key: str, limit: int, window_seconds: int = 60) -> None:
    bucket = int(time.time() // window_seconds)
    full_key = f"rl:{key}:{bucket}"
    client = _redis_client()
    if client is not None:
        count = client.incr(full_key)
        if count == 1:
            client.expire(full_key, window_seconds)
    else:
        with _lock:
            prev_bucket, count = _windows.get(key, (bucket, 0))
            count = count + 1 if prev_bucket == bucket else 1
            _windows[key] = (bucket, count)
    if count > limit:
        raise TooManyRequests("Too many requests. Please wait a minute and try again.")


def reset() -> None:
    with _lock:
        _windows.clear()


def limit_auth(request: Request) -> None:
    hit(f"auth:{client_ip(request)}:{request.url.path}", get_settings().rate_limit_auth_per_minute)
