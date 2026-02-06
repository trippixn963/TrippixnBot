"""
Unified Health Check Server
===========================

Centralized HTTP health check for all bots.
Port and bot name are read from environment variables.

Features:
- Basic health check (Discord connection, latency)
- Optional database health callback
- Optional watchdog/heartbeat callback
- Optional system resources (psutil)
- Optional custom status fields
- Returns 503 for unhealthy status (for monitoring integration)

Environment Variables:
    HEALTH_CHECK_PORT - Port to run on (required, bot-specific)
    BOT_NAME          - Bot name for status response (from .env.shared)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional
from aiohttp import web
from zoneinfo import ZoneInfo

import discord as discord_lib
from src.core.logger import logger

if TYPE_CHECKING:
    import discord


# =============================================================================
# Constants
# =============================================================================

TIMEZONE_NAME = "America/New_York"
EASTERN_TZ = ZoneInfo(TIMEZONE_NAME)
SECONDS_PER_HOUR = 3600
MS_PER_SECOND = 1000

# Type for health check callbacks
HealthCallback = Callable[[], Coroutine[Any, Any, dict]]


# =============================================================================
# Version Helpers
# =============================================================================

def _get_git_commit() -> str:
    """Get the current git commit hash (short form)."""
    try:
        # Try to find the bot's project root by looking for .git directory
        current_dir = Path.cwd()
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=current_dir,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _get_python_version() -> str:
    """Get Python version string."""
    return platform.python_version()


def _get_discord_py_version() -> str:
    """Get discord.py version string."""
    return discord_lib.__version__


# =============================================================================
# Configuration
# =============================================================================

def _get_port() -> int:
    """Get health check port from environment variable."""
    port_str = os.getenv("HEALTH_CHECK_PORT")
    if port_str and port_str.isdigit():
        return int(port_str)
    # Fallback - should not happen in production
    return 8080


def _get_bot_name() -> str:
    """Get bot name from environment variable."""
    return os.getenv("BOT_NAME", "Bot")


# =============================================================================
# Health Check Server
# =============================================================================

class HealthCheckServer:
    """
    Flexible HTTP health check server.

    Provides endpoints for monitoring bot status.
    Supports optional callbacks for extended health data.

    Attributes:
        bot: The Discord bot client.
        port: Port to run the server on.
        start_time: When the server started (for uptime).
    """

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(
        self,
        bot: "discord.Client",
        port: Optional[int] = None,
    ) -> None:
        """
        Initialize health check server.

        Args:
            bot: The Discord bot client.
            port: Port to run on (default: from HEALTH_CHECK_PORT env).
        """
        self.bot = bot
        self.port = port or _get_port()
        self.start_time = datetime.now(EASTERN_TZ)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

        # Optional health check callbacks
        self._db_health_callback: Optional[HealthCallback] = None
        self._watchdog_callback: Optional[HealthCallback] = None
        self._audio_callback: Optional[HealthCallback] = None
        self._system_callback: Optional[HealthCallback] = None
        self._custom_callbacks: dict[str, HealthCallback] = {}

    # =========================================================================
    # Callback Registration
    # =========================================================================

    def register_db_health(self, callback: HealthCallback) -> None:
        """
        Register database health check callback.

        Callback should return dict with at least:
            {"connected": bool, "error": Optional[str]}
        """
        self._db_health_callback = callback

    def register_watchdog(self, callback: HealthCallback) -> None:
        """
        Register watchdog/heartbeat callback.

        Callback should return dict with at least:
            {"heartbeat_fresh": bool, "seconds_since_heartbeat": float}
        """
        self._watchdog_callback = callback

    def register_audio(self, callback: HealthCallback) -> None:
        """
        Register audio status callback.

        Callback should return dict with audio status info.
        """
        self._audio_callback = callback

    def register_system(self, callback: HealthCallback) -> None:
        """
        Register system resources callback (psutil).

        Callback should return dict with system metrics.
        """
        self._system_callback = callback

    def register_custom(self, name: str, callback: HealthCallback) -> None:
        """
        Register a custom health check callback.

        Args:
            name: Key name for the callback in the response.
            callback: Async function returning dict.
        """
        self._custom_callbacks[name] = callback

    # =========================================================================
    # Server Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the health check HTTP server."""
        app = web.Application()
        app.router.add_get("/", self._handle_root)
        app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            "0.0.0.0",
            self.port,
            reuse_address=True,
        )
        await self._site.start()

        logger.tree("Health Check Server Started", [
            ("Port", str(self.port)),
            ("Endpoints", "/, /health"),
        ], emoji="🏥")

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the health check HTTP server with timeout protection.

        Args:
            timeout: Maximum seconds to wait for cleanup (default: 5.0).
        """
        if self._runner:
            try:
                async with asyncio.timeout(timeout):
                    await self._runner.cleanup()
                logger.info("Health Check Server Stopped")
            except asyncio.TimeoutError:
                logger.warning("Health Server Cleanup Timed Out", [
                    ("Timeout", f"{timeout}s"),
                    ("Action", "Forced stop"),
                ])

    # =========================================================================
    # Request Handlers
    # =========================================================================

    async def _handle_root(self, request: web.Request) -> web.Response:
        """Handle root endpoint - simple OK response."""
        return web.Response(text="OK", content_type="text/plain")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """
        Handle /health endpoint - detailed JSON status.

        Returns 503 Service Unavailable if unhealthy.
        """
        now = datetime.now(EASTERN_TZ)
        uptime_seconds = (now - self.start_time).total_seconds()

        # Format uptime as human-readable
        hours, remainder = divmod(int(uptime_seconds), SECONDS_PER_HOUR)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        # Get bot status
        is_ready = self.bot.is_ready()
        latency_ms = round(self.bot.latency * MS_PER_SECOND) if is_ready else None

        # Determine base health status
        health_status = "healthy" if is_ready else "starting"
        is_unhealthy = False

        # Build response
        status: dict[str, Any] = {
            "status": health_status,
            "bot": _get_bot_name(),
            "run_id": getattr(logger, "run_id", None),
            "uptime": uptime_str,
            "uptime_seconds": int(uptime_seconds),
            "started_at": self.start_time.isoformat(),
            "timestamp": now.isoformat(),
            "timezone": "America/New_York (EST)",
            "version": {
                "git_commit": _get_git_commit(),
                "python": _get_python_version(),
                "discord_py": _get_discord_py_version(),
            },
            "discord": {
                "connected": is_ready,
                "latency_ms": latency_ms,
                "guilds": len(self.bot.guilds) if is_ready else 0,
            },
        }

        # Add database health if registered
        if self._db_health_callback:
            try:
                db_status = await self._db_health_callback()
                status["database"] = db_status
                if not db_status.get("connected", True):
                    health_status = "degraded" if is_ready else health_status
            except Exception as e:
                status["database"] = {"connected": False, "error": str(e)}
                health_status = "degraded" if is_ready else health_status

        # Add watchdog health if registered
        if self._watchdog_callback:
            try:
                watchdog_status = await self._watchdog_callback()
                status["watchdog"] = watchdog_status
                if not watchdog_status.get("heartbeat_fresh", True):
                    health_status = "unhealthy"
                    is_unhealthy = True
            except Exception as e:
                status["watchdog"] = {"error": str(e)}

        # Add audio status if registered
        if self._audio_callback:
            try:
                audio_status = await self._audio_callback()
                status["audio"] = audio_status
            except Exception as e:
                status["audio"] = {"error": str(e)}

        # Add system resources if registered
        if self._system_callback:
            try:
                system_status = await self._system_callback()
                status["system"] = system_status
            except Exception as e:
                status["system"] = {"error": str(e)}

        # Add custom callbacks
        for name, callback in self._custom_callbacks.items():
            try:
                custom_status = await callback()
                status[name] = custom_status
            except Exception as e:
                status[name] = {"error": str(e)}

        # Update final status
        status["status"] = health_status

        # Return 503 if unhealthy (helps monitoring tools)
        if is_unhealthy or health_status == "unhealthy":
            return web.json_response(status, status=503)

        return web.json_response(status)


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "HealthCheckServer",
    "HealthCallback",
    "EASTERN_TZ",
]
