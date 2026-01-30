"""
TrippixnBot - Stats API Service
===============================

HTTP API server for portfolio stats.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import os
import re
import time
import aiohttp
from collections import defaultdict
from datetime import datetime, timedelta
from aiohttp import web
from typing import Optional

from src.core import config, log


# =============================================================================
# Rate Limiting
# =============================================================================

class RateLimiter:
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, requests_per_minute: int = 60, burst_limit: int = 10):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Max requests per minute per IP
            burst_limit: Max requests in a 1-second burst
        """
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_ip: str) -> tuple[bool, Optional[int]]:
        """
        Check if request is allowed for this IP.

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        async with self._lock:
            now = time.time()
            window_start = now - 60  # 1 minute window

            # Clean old requests
            self._requests[client_ip] = [
                ts for ts in self._requests[client_ip]
                if ts > window_start
            ]

            requests = self._requests[client_ip]

            # Check per-minute limit
            if len(requests) >= self.requests_per_minute:
                oldest = min(requests) if requests else now
                retry_after = int(oldest + 60 - now) + 1
                return False, retry_after

            # Check burst limit (last 1 second)
            recent = [ts for ts in requests if ts > now - 1]
            if len(recent) >= self.burst_limit:
                return False, 1

            # Allow request
            self._requests[client_ip].append(now)
            return True, None

    async def cleanup(self) -> None:
        """Remove stale entries older than 2 minutes."""
        async with self._lock:
            cutoff = time.time() - 120
            stale_ips = [
                ip for ip, timestamps in self._requests.items()
                if not timestamps or max(timestamps) < cutoff
            ]
            for ip in stale_ips:
                del self._requests[ip]


# Global rate limiter
rate_limiter = RateLimiter(requests_per_minute=60, burst_limit=10)


# =============================================================================
# Stats Storage
# =============================================================================

class StatsStore:
    """Thread-safe stats storage with GitHub commit tracking."""

    def __init__(self):
        self._stats: dict = {
            "guild": {
                "name": "",
                "id": 0,
                "icon": None,
                "banner": None,
                "member_count": 0,
                "online_count": 0,
                "boost_level": 0,
                "boost_count": 0,
                "messages_this_week": 0,
                "chat_active": False,
                "created_at": None,
                "members_gained_this_week": 0,
                "moderators": [],
            },
            "bots": {
                "taha": {"online": False},
                "othman": {"online": False},
            },
            "developer": {"status": "offline", "avatar": None, "banner": None, "decoration": None, "activities": []},
            "commits": {
                "this_year": 0,
                "year_start": None,
                "last_fetched": None,
            },
            "updated_at": None,
        }
        self._lock = asyncio.Lock()
        self._commits_file = "/root/TrippixnBot/data/commits.json"
        self._github_task: Optional[asyncio.Task] = None
        self._load_commits()

    def _load_commits(self) -> None:
        """Load cached commits from file."""
        try:
            if os.path.exists(self._commits_file):
                with open(self._commits_file, "r") as f:
                    data = json.load(f)
                    self._stats["commits"] = data
        except Exception as e:
            log.warning(f"Failed to load commits cache: {e}")

    def _save_commits(self) -> None:
        """Save commits to cache file."""
        try:
            os.makedirs(os.path.dirname(self._commits_file), exist_ok=True)
            with open(self._commits_file, "w") as f:
                json.dump(self._stats["commits"], f)
        except Exception as e:
            log.warning(f"Failed to save commits cache: {e}")

    async def fetch_github_commits(self) -> int:
        """Fetch total commits this year from GitHub using GraphQL API (single request)."""
        username = config.GITHUB_USERNAME
        token = config.GITHUB_TOKEN

        if not username:
            log.warning("GITHUB_USERNAME not set")
            return self._stats["commits"].get("this_year", 0)

        if not token:
            log.warning("GITHUB_TOKEN not set - required for GraphQL API")
            return self._stats["commits"].get("this_year", 0)

        # GraphQL query to get contribution calendar
        query = """
        query($username: String!, $from: DateTime!, $to: DateTime!) {
            user(login: $username) {
                contributionsCollection(from: $from, to: $to) {
                    totalCommitContributions
                    restrictedContributionsCount
                }
            }
        }
        """

        now = datetime.now()
        year_start = datetime(now.year, 1, 1)

        variables = {
            "username": username,
            "from": year_start.isoformat() + "Z",
            "to": now.isoformat() + "Z",
        }

        headers = {
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.github.com/graphql",
                    json={"query": query, "variables": variables},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        log.warning(f"GitHub GraphQL API error: {resp.status}")
                        return self._stats["commits"].get("this_year", 0)

                    data = await resp.json()

                    if "errors" in data:
                        log.warning(f"GitHub GraphQL error: {data['errors']}")
                        return self._stats["commits"].get("this_year", 0)

                    user_data = data.get("data", {}).get("user", {})
                    contributions = user_data.get("contributionsCollection", {})

                    # Total commits = public + private (restricted)
                    public_commits = contributions.get("totalCommitContributions", 0)
                    private_commits = contributions.get("restrictedContributionsCount", 0)
                    total_commits = public_commits + private_commits

                    # Update stats
                    async with self._lock:
                        self._stats["commits"]["this_year"] = total_commits
                        self._stats["commits"]["year_start"] = year_start.strftime("%Y-%m-%d")
                        self._stats["commits"]["last_fetched"] = now.isoformat()
                        self._save_commits()

                    log.success(f"GitHub commits updated: {total_commits} commits in {now.year} (GraphQL)")
                    return total_commits

        except Exception as e:
            log.warning(f"Failed to fetch GitHub commits: {e}")
            return self._stats["commits"].get("this_year", 0)

    async def start_github_polling(self) -> None:
        """Start background task to periodically fetch GitHub commits."""
        async def poll_loop():
            while True:
                await self.fetch_github_commits()
                # Update every hour (GitHub API rate limit is 5000/hour with token)
                await asyncio.sleep(3600)

        # Fetch immediately on startup
        await self.fetch_github_commits()
        # Then start the polling loop
        self._github_task = asyncio.create_task(poll_loop())

    async def stop_github_polling(self) -> None:
        """Stop the GitHub polling task."""
        if self._github_task:
            self._github_task.cancel()
            try:
                await self._github_task
            except asyncio.CancelledError:
                pass

    async def update(self, **kwargs) -> None:
        """Update stats."""
        async with self._lock:
            for key, value in kwargs.items():
                if key in self._stats:
                    if isinstance(value, dict):
                        self._stats[key].update(value)
                    else:
                        self._stats[key] = value

    async def get(self) -> dict:
        """Get current stats (async)."""
        async with self._lock:
            return self._stats.copy()

    def get_stats(self) -> dict:
        """Get current stats (sync) - for use in non-async contexts."""
        return self._stats.copy()


# Global stats store
stats_store = StatsStore()


# =============================================================================
# Security Middleware
# =============================================================================

def get_client_ip(request: web.Request) -> str:
    """Extract client IP from request, handling proxies."""
    # Check for forwarded headers (behind reverse proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For can contain multiple IPs, first is the client
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to direct connection IP
    peername = request.transport.get_extra_info("peername")
    if peername:
        return peername[0]

    return "unknown"


@web.middleware
async def rate_limit_middleware(request: web.Request, handler) -> web.Response:
    """Middleware to enforce rate limiting on all requests."""
    # Skip rate limiting for health checks
    if request.path == "/health":
        return await handler(request)

    client_ip = get_client_ip(request)
    allowed, retry_after = await rate_limiter.is_allowed(client_ip)

    if not allowed:
        log.warning("Rate Limit Exceeded", [
            ("IP", client_ip),
            ("Path", request.path),
            ("Retry-After", f"{retry_after}s"),
        ])
        return web.json_response(
            {"error": "Rate limit exceeded", "retry_after": retry_after},
            status=429,
            headers={
                "Retry-After": str(retry_after),
                "Access-Control-Allow-Origin": "*",
            }
        )

    return await handler(request)


@web.middleware
async def security_headers_middleware(request: web.Request, handler) -> web.Response:
    """Middleware to add security headers to all responses."""
    response = await handler(request)

    # Add security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response


# =============================================================================
# API Handlers
# =============================================================================

async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/stats - Return server stats."""
    stats = await stats_store.get()
    return web.json_response(stats, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=30",
    })


async def handle_commits_refresh(request: web.Request) -> web.Response:
    """POST /api/commits/refresh - Manually refresh GitHub commit count (requires API key)."""
    # Verify API key
    api_key = request.headers.get("X-API-Key")
    expected_key = os.environ.get("COMMITS_API_KEY", "")

    if not expected_key or api_key != expected_key:
        return web.json_response(
            {"error": "Unauthorized"},
            status=401,
            headers={"Access-Control-Allow-Origin": "*"}
        )

    # Fetch fresh commit count from GitHub
    new_total = await stats_store.fetch_github_commits()

    return web.json_response(
        {"commits_this_year": new_total},
        headers={"Access-Control-Allow-Origin": "*"}
    )


# handle_health moved to StatsAPI.handle_health method for bot access


# Discord User ID for avatar endpoint
DISCORD_USER_ID = "259725211664908288"
LANYARD_URL = f"https://api.lanyard.rest/v1/users/{DISCORD_USER_ID}"

# Cache for avatar URL (refresh every 5 minutes)
_avatar_cache: dict = {"url": None, "expires": 0}


async def handle_avatar(request: web.Request) -> web.Response:
    """GET /avatar - Redirect to current Discord avatar."""
    global _avatar_cache

    now = time.time()

    # Check cache
    if _avatar_cache["url"] and now < _avatar_cache["expires"]:
        return web.HTTPFound(_avatar_cache["url"])

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LANYARD_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success") and data.get("data", {}).get("discord_user"):
                        user = data["data"]["discord_user"]
                        avatar_hash = user.get("avatar")
                        user_id = user.get("id", DISCORD_USER_ID)

                        if avatar_hash:
                            # Determine format (animated avatars start with a_)
                            ext = "gif" if avatar_hash.startswith("a_") else "png"
                            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=512"

                            # Cache for 5 minutes
                            _avatar_cache = {"url": avatar_url, "expires": now + 300}

                            return web.HTTPFound(avatar_url)

        # Fallback to default Discord avatar
        return web.HTTPFound(f"https://cdn.discordapp.com/embed/avatars/0.png")

    except Exception as e:
        log.warning(f"Failed to fetch avatar: {e}")
        # Return cached URL if available, otherwise default
        if _avatar_cache["url"]:
            return web.HTTPFound(_avatar_cache["url"])
        return web.HTTPFound(f"https://cdn.discordapp.com/embed/avatars/0.png")


# =============================================================================
# API Server
# =============================================================================

class StatsAPI:
    """Stats API server."""

    def __init__(self, bot=None):
        self._bot = bot
        self._start_time: Optional[datetime] = None
        self.app = web.Application(middlewares=[
            rate_limit_middleware,
            security_headers_middleware,
        ])
        self.runner: Optional[web.AppRunner] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._setup_routes()

    def set_bot(self, bot) -> None:
        """Set bot reference after initialization."""
        self._bot = bot

    def _setup_routes(self) -> None:
        """Configure API routes."""
        self.app.router.add_get("/api/stats", handle_stats)
        self.app.router.add_post("/api/commits/refresh", handle_commits_refresh)
        self.app.router.add_get("/avatar", handle_avatar)
        # /health removed - now served by unified HealthCheckServer on port 8087

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /health - Health check endpoint with full status."""
        from zoneinfo import ZoneInfo
        EST_TZ = ZoneInfo("America/New_York")

        now = datetime.now(EST_TZ)
        start = self._start_time or now
        uptime_seconds = (now - start).total_seconds()

        # Format uptime as human-readable
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        # Get bot status
        is_ready = self._bot.is_ready() if self._bot else False
        latency_ms = round(self._bot.latency * 1000) if self._bot and is_ready else None

        status = {
            "status": "healthy" if is_ready else "starting",
            "bot": "TrippixnBot",
            "run_id": getattr(log, "run_id", None),
            "uptime": uptime_str,
            "uptime_seconds": int(uptime_seconds),
            "started_at": start.isoformat(),
            "timestamp": now.isoformat(),
            "timezone": "America/New_York (EST)",
            "discord": {
                "connected": is_ready,
                "latency_ms": latency_ms,
                "guilds": len(self._bot.guilds) if self._bot and is_ready else 0,
            },
        }

        return web.json_response(status)

    async def _periodic_cleanup(self) -> None:
        """Periodically cleanup rate limiter stale entries."""
        while True:
            await asyncio.sleep(120)  # Every 2 minutes
            await rate_limiter.cleanup()

    async def start(self) -> None:
        """Start the API server."""
        from zoneinfo import ZoneInfo
        self._start_time = datetime.now(ZoneInfo("America/New_York"))

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(
            self.runner,
            config.API_HOST,
            config.API_PORT
        )
        await site.start()

        # Start periodic cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        # Start GitHub commit polling
        await stats_store.start_github_polling()

        log.tree("Stats API Started", [
            ("Host", config.API_HOST),
            ("Port", config.API_PORT),
            ("Endpoints", "/api/stats, /health"),
            ("Rate Limit", "60 req/min, 10 burst"),
            ("GitHub", f"Tracking @{config.GITHUB_USERNAME}"),
        ], emoji="🌐")

    async def stop(self) -> None:
        """Stop the API server."""
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Stop GitHub polling
        await stats_store.stop_github_polling()

        if self.runner:
            await self.runner.cleanup()
            log.success("Stats API Stopped")
