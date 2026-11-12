"""Fixed-window rate limiting.

Applied per agent credential and per dashboard user so one noisy caller cannot
starve the policy decision endpoint. State is process-local, which is correct
for the single-process development and demo deployment; a multi-instance
deployment should back this with Redis (see the README).

The limiter fails *closed* for sensitive endpoints: when a limit is exceeded
the request is rejected, never silently allowed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

from fastapi import Request

from .errors import ApiError


@dataclass
class Bucket:
    count: int = 0
    reset_at: float = 0.0


@dataclass
class RateLimiter:
    """Fixed-window counter keyed by an arbitrary identity string."""

    limit: int
    window_seconds: float
    _buckets: dict[str, Bucket] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def _now(self) -> float:
        return time.monotonic()

    def allow(self, key: str) -> tuple[bool, int, float]:
        """Return ``(allowed, remaining, retry_after_seconds)``."""
        now = self._now()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.reset_at <= now:
                bucket = Bucket(count=0, reset_at=now + self.window_seconds)
                self._buckets[key] = bucket

            if bucket.count >= self.limit:
                retry_after = max(0.0, bucket.reset_at - now)
                return False, 0, retry_after

            bucket.count += 1
            remaining = self.limit - bucket.count
            return True, remaining, 0.0

    def prune(self) -> int:
        """Drop expired buckets. Returns the number removed."""
        now = self._now()
        with self._lock:
            expired = [key for key, bucket in self._buckets.items() if bucket.reset_at <= now]
            for key in expired:
                del self._buckets[key]
            return len(expired)


class RateLimitExceeded(ApiError):
    def __init__(self, retry_after: float):
        super().__init__(
            f"Rate limit exceeded. Retry in {int(retry_after) + 1} seconds.",
            status_code=429,
            reason_codes=["RATE_LIMIT_EXCEEDED"],
        )
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(int(retry_after) + 1)}


def client_key(request: Request, identifier: str | None = None) -> str:
    """Build a limiter key from the caller's identity and address."""
    if identifier:
        return identifier
    forwarded = request.headers.get("x-forwarded-for")
    address = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else "unknown"
    return f"{address}:{request.url.path}"


def check_rate_limit(
    limiter: RateLimiter,
    request: Request,
    identifier: str | None = None,
) -> None:
    """Raise :class:`RateLimitExceeded` when the caller is over the limit."""
    allowed, _remaining, retry_after = limiter.allow(client_key(request, identifier))
    if not allowed:
        raise RateLimitExceeded(retry_after)
