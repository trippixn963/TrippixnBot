"""
TrippixnBot - Rate Limiting Middleware
======================================

Token bucket rate limiting for API endpoints.

Author: حَـــــنَّـــــا
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from src.core import log
from src.api.config import get_api_config


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""

    capacity: int
    tokens: float = field(default=0)
    last_update: float = field(default_factory=time.time)
    refill_rate: float = 1.0

    def __post_init__(self):
        self.tokens = float(self.capacity)

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        now = time.time()
        elapsed = now - self.last_update
        self.last_update = now

        # Refill tokens
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def retry_after(self) -> float:
        """Seconds until a token is available."""
        if self.tokens >= 1:
            return 0
        return (1 - self.tokens) / self.refill_rate


class RateLimiter:
    """Manages rate limiting across clients."""

    def __init__(self, default_limit: int = 60, default_window: int = 60):
        self._default_limit = default_limit
        self._default_window = default_window
        self._buckets: dict[str, TokenBucket] = {}
        self._last_cleanup = time.time()

    def check(self, client_ip: str, path: str) -> tuple[bool, Optional[float], int, int]:
        """Check if request is allowed. Returns (allowed, retry_after, remaining, limit)."""
        self._cleanup_stale_buckets()

        key = f"ip:{client_ip}:{path}"
        limit = self._default_limit
        window = self._default_window

        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                capacity=limit,
                refill_rate=limit / window,
            )

        bucket = self._buckets[key]
        allowed = bucket.consume()

        return (
            allowed,
            bucket.retry_after if not allowed else None,
            int(bucket.tokens),
            limit,
        )

    def _cleanup_stale_buckets(self) -> None:
        """Remove buckets unused for 10 minutes."""
        now = time.time()
        if now - self._last_cleanup < 300:
            return

        self._last_cleanup = now
        stale = [k for k, b in self._buckets.items() if b.last_update < now - 600]
        for key in stale:
            del self._buckets[key]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting."""

    SKIP_PATHS = {"/health"}

    def __init__(self, app, rate_limiter: Optional["RateLimiter"] = None):
        super().__init__(app)
        self._limiter = rate_limiter or get_rate_limiter()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        path = request.url.path

        allowed, retry_after, remaining, limit = self._limiter.check(client_ip, path)

        if not allowed:
            log.debug("Rate Limit Exceeded", [
                ("IP", client_ip),
                ("Path", path),
                ("Retry", f"{retry_after:.1f}s"),
            ])
            return Response(
                content='{"error": "Rate limit exceeded"}',
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
                headers={
                    "Retry-After": str(int(retry_after or 1)),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, handling proxies."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"


_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create rate limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        config = get_api_config()
        _rate_limiter = RateLimiter(
            default_limit=config.rate_limit_requests,
            default_window=config.rate_limit_window,
        )
    return _rate_limiter


__all__ = ["RateLimitMiddleware", "RateLimiter", "get_rate_limiter"]
