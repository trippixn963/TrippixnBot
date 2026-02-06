"""
TrippixnBot - Health Router
===========================

Health check endpoint.

Author: حَـــــنَّـــــا
"""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from src.core import log
from src.api.models.base import APIResponse
from src.api.models.stats import HealthStatus, DiscordStatus


router = APIRouter(tags=["Health"])

EST_TZ = ZoneInfo("America/New_York")


@router.get("/health", response_model=APIResponse[HealthStatus])
async def health_check(request: Request) -> APIResponse[HealthStatus]:
    """
    Health check endpoint with full status.

    Returns bot status, uptime, and Discord connection info.
    """
    api_service = request.app.state.api_service
    bot = api_service.bot if api_service else None
    start_time = api_service.start_time if api_service else None

    now = datetime.now(EST_TZ)
    start = start_time or now
    uptime_seconds = (now - start).total_seconds()

    # Format uptime
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    # Bot status
    is_ready = bot.is_ready() if bot else False
    latency = bot.latency if bot and is_ready else None
    latency_ms = round(latency * 1000) if latency and not math.isinf(latency) else None

    discord_status = DiscordStatus(
        connected=is_ready,
        latency_ms=latency_ms,
        guilds=len(bot.guilds) if bot and is_ready else 0,
    )

    health = HealthStatus(
        status="healthy" if is_ready else "starting",
        uptime=uptime_str,
        uptime_seconds=int(uptime_seconds),
        started_at=start.isoformat(),
        timestamp=now.isoformat(),
        discord=discord_status,
    )

    log.debug("Health Check", [
        ("Status", health.status),
        ("Latency", f"{latency_ms}ms" if latency_ms else "N/A"),
    ])

    return APIResponse(success=True, data=health)


__all__ = ["router"]
