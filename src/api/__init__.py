"""
TrippixnBot - API Package
=========================

FastAPI-based API for portfolio stats.

Author: حَـــــنَّـــــا
Server: discord.gg/syria

Features:
- GitHub contribution stats
- Discord avatar redirect
- Rate limiting and request logging
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

import uvicorn

from src.core import log
from src.api.config import get_api_config, APIConfig
from src.api.app import create_app

if TYPE_CHECKING:
    from src.bot import TrippixnBot


# =============================================================================
# API Service
# =============================================================================

class APIService:
    """
    Manages the FastAPI server lifecycle within the Discord bot.

    This service runs the API server in a background task, allowing
    the bot and API to run concurrently.
    """

    def __init__(self) -> None:
        self._bot: Optional["TrippixnBot"] = None
        self._config = get_api_config()
        self._server: Optional[uvicorn.Server] = None
        self._task: Optional[asyncio.Task] = None
        self._start_time: Optional[datetime] = None

    def set_bot(self, bot: "TrippixnBot") -> None:
        """Set bot reference for API endpoints."""
        self._bot = bot

    @property
    def bot(self) -> Optional["TrippixnBot"]:
        """Get the bot instance."""
        return self._bot

    @property
    def start_time(self) -> Optional[datetime]:
        """Get the API start time."""
        return self._start_time

    @property
    def is_running(self) -> bool:
        """Check if the API server is running."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the FastAPI server in a background task."""
        from src.api.services.stats_store import get_stats_store

        if self.is_running:
            log.warning("API Already Running", [])
            return

        self._start_time = datetime.now(ZoneInfo("America/New_York"))

        # Create app with bot reference
        app = create_app(self)

        # Start GitHub polling
        stats_store = get_stats_store()
        await stats_store.start_github_polling()

        # Configure uvicorn
        config = uvicorn.Config(
            app=app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )

        self._server = uvicorn.Server(config)

        # Run in background
        self._task = asyncio.create_task(self._run_server())

        log.tree("API Started", [
            ("Host", self._config.host),
            ("Port", str(self._config.port)),
            ("Endpoints", "/api/stats, /avatar, /health"),
            ("Rate Limit", f"{self._config.rate_limit_requests}/min"),
        ], emoji="🌐")

    async def _run_server(self) -> None:
        """Run the uvicorn server."""
        try:
            await self._server.serve()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("API Server Error", [("Error", str(e)[:100])])

    async def stop(self) -> None:
        """Stop the FastAPI server gracefully."""
        from src.api.services.stats_store import get_stats_store

        if not self.is_running:
            return

        log.tree("API Stopping", [], emoji="🛑")

        # Stop GitHub polling
        stats_store = get_stats_store()
        await stats_store.stop_github_polling()

        # Signal server to stop
        if self._server:
            self._server.should_exit = True

        # Wait for task to complete
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        self._server = None
        self._task = None

        log.tree("API Stopped", [], emoji="✅")


# Singleton instance
_api_service: Optional[APIService] = None


def get_api_service() -> APIService:
    """Get the API service singleton."""
    global _api_service
    if _api_service is None:
        _api_service = APIService()
    return _api_service


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main service
    "APIService",
    "get_api_service",
    # Config
    "get_api_config",
    "APIConfig",
    # App factory
    "create_app",
]
