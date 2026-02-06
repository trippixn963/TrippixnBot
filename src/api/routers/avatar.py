"""
TrippixnBot - Avatar Router
===========================

Discord avatar redirect endpoint.
Uses server-specific avatar (guild avatar) from cached stats.

Author: حَـــــنَّـــــا
"""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from src.core import log
from src.api.services.stats_store import get_stats_store


router = APIRouter(tags=["Avatar"])

# Default avatar fallback
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"


@router.get("/avatar")
async def get_avatar() -> RedirectResponse:
    """
    Redirect to current Discord server avatar.

    Uses the cached server-specific avatar (guild avatar) from stats.
    Falls back to default if not available.
    """
    stats_store = get_stats_store()
    stats = stats_store.get_sync()

    # Get developer's server avatar from cached stats
    dev_avatar = stats.get("developer", {}).get("avatar")

    if dev_avatar:
        log.debug("Avatar Redirect", [("Source", "Stats Cache")])
        return RedirectResponse(url=dev_avatar)

    log.debug("Avatar Redirect", [("Source", "Default")])
    return RedirectResponse(url=DEFAULT_AVATAR)


__all__ = ["router"]
