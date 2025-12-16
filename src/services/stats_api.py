"""
TrippixnBot - Stats API Service
===============================

HTTP API server for portfolio stats.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
from aiohttp import web
from typing import Optional

from src.core import config, log


# =============================================================================
# Stats Storage
# =============================================================================

class StatsStore:
    """Thread-safe stats storage."""

    def __init__(self):
        self._stats: dict = {
            "guild": {
                "name": "",
                "id": 0,
                "member_count": 0,
                "online_count": 0,
                "boost_level": 0,
                "boost_count": 0,
            },
            "bots": {
                "taha": {"online": False},
                "othman": {"online": False},
            },
            "developer": {"status": "offline", "avatar": None, "banner": None, "decoration": None, "activities": []},
            "updated_at": None,
        }
        self._lock = asyncio.Lock()

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
# API Handlers
# =============================================================================

async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/stats - Return server stats."""
    stats = await stats_store.get()
    return web.json_response(stats, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=30",
    })


async def handle_health(request: web.Request) -> web.Response:
    """GET /health - Health check endpoint."""
    return web.json_response({"status": "healthy"})


# =============================================================================
# API Server
# =============================================================================

class StatsAPI:
    """Stats API server."""

    def __init__(self):
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Configure API routes."""
        self.app.router.add_get("/api/stats", handle_stats)
        self.app.router.add_get("/health", handle_health)

    async def start(self) -> None:
        """Start the API server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        site = web.TCPSite(
            self.runner,
            config.API_HOST,
            config.API_PORT
        )
        await site.start()
        log.tree("Stats API Started", [
            ("Host", config.API_HOST),
            ("Port", config.API_PORT),
            ("Endpoints", "/api/stats, /health"),
        ], emoji="🌐")

    async def stop(self) -> None:
        """Stop the API server."""
        if self.runner:
            await self.runner.cleanup()
            log.success("Stats API Stopped")
