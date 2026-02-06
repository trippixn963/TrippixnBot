"""
TrippixnBot - Stats Models
==========================

Pydantic models for portfolio stats.

Author: حَـــــنَّـــــا
"""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel


class ModeratorRole(BaseModel):
    """Moderator role info."""

    name: str
    color: Optional[str] = None


class ModeratorInfo(BaseModel):
    """Moderator data for dashboard."""

    id: str
    username: str
    display_name: str
    avatar: str
    banner: Optional[str] = None
    accent_color: Optional[str] = None
    status: str
    role_color: Optional[str] = None
    roles: List[ModeratorRole] = []
    joined_at: Optional[str] = None
    created_at: Optional[str] = None


class GuildStats(BaseModel):
    """Discord guild statistics."""

    name: str
    id: int
    icon: Optional[str] = None
    banner: Optional[str] = None
    member_count: int = 0
    online_count: int = 0
    boost_level: int = 0
    boost_count: int = 0
    total_messages: int = 0
    chat_active: bool = False
    created_at: Optional[str] = None
    moderators: List[ModeratorInfo] = []


class BotStatus(BaseModel):
    """Bot online status."""

    online: bool = False


class BotsInfo(BaseModel):
    """Status of tracked bots."""

    taha: BotStatus
    othman: BotStatus


class ActivityInfo(BaseModel):
    """Discord activity data."""

    type: str
    name: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_cover: Optional[str] = None
    track_url: Optional[str] = None
    emoji: Optional[str] = None
    details: Optional[str] = None
    state: Optional[str] = None
    url: Optional[str] = None
    game: Optional[str] = None
    platform: Optional[str] = None
    large_image: Optional[str] = None
    small_image: Optional[str] = None


class DeveloperInfo(BaseModel):
    """Developer presence info."""

    status: str = "offline"
    avatar: Optional[str] = None
    banner: Optional[str] = None
    decoration: Optional[str] = None
    activities: List[ActivityInfo] = []


class CommitsInfo(BaseModel):
    """GitHub commit stats."""

    this_year: int = 0
    year_start: Optional[str] = None
    last_fetched: Optional[str] = None
    calendar: List[Any] = []


class PortfolioStats(BaseModel):
    """Complete portfolio stats response."""

    guild: GuildStats
    bots: BotsInfo
    developer: DeveloperInfo
    commits: CommitsInfo
    updated_at: Optional[str] = None


class DiscordStatus(BaseModel):
    """Discord connection status."""

    connected: bool = False
    latency_ms: Optional[int] = None
    guilds: int = 0


class HealthStatus(BaseModel):
    """Health check response."""

    status: str
    bot: str = "TrippixnBot"
    uptime: str
    uptime_seconds: int
    started_at: str
    timestamp: str
    timezone: str = "America/New_York (EST)"
    discord: DiscordStatus


__all__ = [
    "ModeratorRole",
    "ModeratorInfo",
    "GuildStats",
    "BotStatus",
    "BotsInfo",
    "ActivityInfo",
    "DeveloperInfo",
    "CommitsInfo",
    "PortfolioStats",
    "DiscordStatus",
    "HealthStatus",
]
