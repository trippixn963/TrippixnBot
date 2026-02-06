"""
TrippixnBot - Stats Router
==========================

Portfolio stats endpoints.

Author: حَـــــنَّـــــا
"""

from fastapi import APIRouter, Header, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

from src.core import log
from src.api.config import get_api_config
from src.api.services.stats_store import get_stats_store
from src.api.models.base import APIResponse
from src.api.models.stats import PortfolioStats


router = APIRouter(tags=["Stats"])


@router.get("/stats", response_model=APIResponse[PortfolioStats])
async def get_stats() -> APIResponse[PortfolioStats]:
    """
    Get portfolio stats.

    Returns guild info, bot status, developer presence, and GitHub commits.
    Public endpoint with 30-second cache.
    """
    stats_store = get_stats_store()
    stats = await stats_store.get()

    log.debug("Stats Fetched", [
        ("Members", str(stats.get("guild", {}).get("member_count", 0))),
        ("Commits", str(stats.get("commits", {}).get("this_year", 0))),
    ])

    return APIResponse(success=True, data=stats)


@router.post("/commits/refresh", response_model=APIResponse[dict])
async def refresh_commits(
    x_api_key: str = Header(None, alias="X-API-Key"),
) -> APIResponse[dict]:
    """
    Manually refresh GitHub commit count.

    Requires API key authentication.
    """
    config = get_api_config()

    if not config.commits_api_key or x_api_key != config.commits_api_key:
        log.warning("Commits Refresh Denied", [("Reason", "Invalid API key")])
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )

    stats_store = get_stats_store()
    new_total = await stats_store.refresh_github_commits()

    log.tree("Commits Refreshed", [
        ("Total", str(new_total)),
    ], emoji="🔄")

    return APIResponse(success=True, data={"commits_this_year": new_total})


__all__ = ["router"]
