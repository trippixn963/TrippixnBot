"""
TrippixnBot - Ready Handler
===========================

Handles bot ready event and stats collection for dashboard.

Author: حَـــــنَّـــــا
"""

import asyncio
import discord
from discord.ext import tasks
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from src.core import config, log
from src.services import get_stats_store, member_tracker
from src.utils.http import http_session


# =============================================================================
# Constants
# =============================================================================

EST = ZoneInfo("America/New_York")

STATUS_MAP = {
    discord.Status.online: "online",
    discord.Status.idle: "idle",
    discord.Status.dnd: "dnd",
    discord.Status.offline: "offline",
}


# =============================================================================
# Moderator Cache
# =============================================================================

_moderator_cache: List[Dict[str, Any]] = []
_moderator_cache_updated: Optional[datetime] = None


async def fetch_moderator_data(bot: discord.Client) -> List[Dict[str, Any]]:
    """Fetch moderator data including banners."""
    global _moderator_cache, _moderator_cache_updated

    guild = bot.get_guild(config.GUILD_ID)
    if not guild:
        return []

    moderators = []
    mod_role = guild.get_role(config.MODERATOR_ROLE_ID)
    if not mod_role:
        return []

    sorted_members = sorted(
        [m for m in mod_role.members if not m.bot],
        key=lambda m: m.top_role.position,
        reverse=True
    )

    for member in sorted_members:
        avatar_url = member.display_avatar.with_size(512).url
        member_status = STATUS_MAP.get(member.status, "offline")

        top_role = member.top_role
        role_color = None
        if top_role and top_role.color.value != 0:
            role_color = f"#{top_role.color.value:06x}"

        member_roles = [
            {"name": r.name, "color": f"#{r.color.value:06x}" if r.color.value != 0 else None}
            for r in sorted(member.roles[1:], key=lambda r: r.position, reverse=True)
            if not r.is_default()
        ][:5]

        mod_data = {
            "id": str(member.id),
            "username": member.name,
            "display_name": member.display_name,
            "avatar": avatar_url,
            "banner": None,
            "status": member_status,
            "role_color": role_color,
            "roles": member_roles,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "created_at": member.created_at.isoformat() if member.created_at else None,
        }

        try:
            user = await bot.fetch_user(member.id)
            if user.banner:
                mod_data["banner"] = user.banner.with_size(512).url
            if user.accent_color is not None and user.accent_color.value != 0:
                mod_data["accent_color"] = f"#{user.accent_color.value:06x}"
        except Exception as e:
            log.warning(f"Banner fetch failed for {member.display_name}: {e}")

        moderators.append(mod_data)

    _moderator_cache = moderators
    _moderator_cache_updated = datetime.now(EST)

    log.tree("Moderator Cache Updated", [
        ("Total Mods", len(moderators)),
        ("With Banners", len([m for m in moderators if m.get("banner")])),
    ], emoji="👥")

    return moderators


def get_cached_moderators() -> List[Dict[str, Any]]:
    """Get cached moderator data."""
    return _moderator_cache.copy()


async def _wait_until_midnight_est() -> None:
    """Wait until the next midnight EST."""
    now = datetime.now(EST)
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=EST)
    wait_seconds = (midnight - now).total_seconds()
    log.info(f"Next moderator refresh in {wait_seconds / 3600:.1f} hours")
    await asyncio.sleep(wait_seconds)


@tasks.loop(hours=24)
async def refresh_moderator_cache(bot: discord.Client) -> None:
    """Refresh moderator cache daily at midnight EST."""
    await fetch_moderator_data(bot)


@refresh_moderator_cache.before_loop
async def before_refresh_moderator_cache() -> None:
    """Wait until midnight EST before starting the daily loop."""
    await _wait_until_midnight_est()


# =============================================================================
# Developer Presence Cache
# =============================================================================

_dev_presence_cache = {
    "status": "offline",
    "activities": [],
}


def _parse_activities(activities: tuple) -> list:
    """Parse discord activities into serializable format."""
    result = []
    for activity in activities:
        activity_data = {"type": activity.type.name}

        if isinstance(activity, discord.CustomActivity):
            activity_data["type"] = "custom"
            activity_data["name"] = activity.name
            activity_data["emoji"] = str(activity.emoji) if activity.emoji else None
        elif isinstance(activity, discord.Spotify):
            activity_data["type"] = "spotify"
            activity_data["title"] = activity.title
            activity_data["artist"] = activity.artist
            activity_data["album"] = activity.album
            activity_data["album_cover"] = activity.album_cover_url
            activity_data["track_url"] = f"https://open.spotify.com/track/{activity.track_id}"
        elif isinstance(activity, discord.Game):
            activity_data["type"] = "playing"
            activity_data["name"] = activity.name
        elif isinstance(activity, discord.Streaming):
            activity_data["type"] = "streaming"
            activity_data["name"] = activity.name
            activity_data["game"] = activity.game
            activity_data["url"] = activity.url
            activity_data["platform"] = activity.platform
        elif isinstance(activity, discord.Activity):
            activity_data["name"] = activity.name
            if activity.details:
                activity_data["details"] = activity.details
            if activity.state:
                activity_data["state"] = activity.state
            if activity.large_image_url:
                activity_data["large_image"] = activity.large_image_url
            if activity.small_image_url:
                activity_data["small_image"] = activity.small_image_url

        result.append(activity_data)
    return result


# =============================================================================
# Presence Update Handler
# =============================================================================

async def on_presence_update(bot: discord.Client, before: discord.Member, after: discord.Member) -> None:
    """Handle presence updates - cache developer's activities for dashboard."""
    global _dev_presence_cache

    if after.id != config.OWNER_ID:
        return

    new_status = STATUS_MAP.get(after.status, "offline")
    _dev_presence_cache["status"] = new_status
    _dev_presence_cache["activities"] = _parse_activities(after.activities)

    log.debug("Developer Presence Updated", [
        ("Status", new_status),
        ("Activities", len(_dev_presence_cache["activities"])),
    ])


# =============================================================================
# Ready Handler
# =============================================================================

async def on_ready(bot: discord.Client) -> None:
    """Handle bot ready event."""
    await bot.change_presence(status=discord.Status.invisible)

    log.startup_banner(
        bot_name="TrippixnBot",
        bot_id=bot.user.id,
        guilds=len(bot.guilds),
        latency=bot.latency * 1000,
    )

    guild = bot.get_guild(config.GUILD_ID)

    # Cache initial developer status
    if guild:
        dev_member = guild.get_member(config.OWNER_ID)
        if dev_member:
            _dev_presence_cache["status"] = STATUS_MAP.get(dev_member.status, "offline")
            _dev_presence_cache["activities"] = _parse_activities(dev_member.activities)

    # Update member tracker
    if guild:
        member_tracker.update(guild.member_count)

    # Fetch moderator data
    await fetch_moderator_data(bot)

    # Start daily moderator refresh
    if not refresh_moderator_cache.is_running():
        refresh_moderator_cache.start(bot)

    # Start stats collection
    if not collect_stats.is_running():
        collect_stats.start(bot)


# =============================================================================
# Stats Collection Task
# =============================================================================

@tasks.loop(seconds=config.STATS_UPDATE_INTERVAL)
async def collect_stats(bot: discord.Client) -> None:
    """Collect and update server stats for dashboard."""
    global _dev_presence_cache

    try:
        guild = bot.get_guild(config.GUILD_ID)
        if not guild:
            return

        # Count online members
        online_count = sum(
            1 for m in guild.members
            if m.status != discord.Status.offline and not m.bot
        )

        # Check bot statuses
        taha_member = guild.get_member(config.TAHA_BOT_ID)
        othman_member = guild.get_member(config.OTHMAN_BOT_ID)

        taha_online = taha_member and taha_member.status != discord.Status.offline
        othman_online = othman_member and othman_member.status != discord.Status.offline

        # Developer info (server-specific where possible)
        dev_member = guild.get_member(config.OWNER_ID)
        dev_status = "offline"
        dev_avatar = None
        dev_banner = None
        dev_decoration = None
        dev_activities = []

        if dev_member:
            dev_status = STATUS_MAP.get(dev_member.status, "offline")

            # Use display_avatar which returns guild avatar if set, otherwise global
            dev_avatar = dev_member.display_avatar.with_size(512).url

            if dev_member.avatar_decoration:
                dev_decoration = dev_member.avatar_decoration.url

            # Banner is global only (Discord doesn't support server-specific banners)
            try:
                dev_user = await bot.fetch_user(config.OWNER_ID)
                if dev_user.banner:
                    dev_banner = dev_user.banner.with_size(1024).url
            except Exception:
                pass

            if dev_member.activities:
                dev_activities = _parse_activities(dev_member.activities)
                _dev_presence_cache["status"] = dev_status
                _dev_presence_cache["activities"] = dev_activities
            else:
                dev_activities = _dev_presence_cache["activities"]

        # Guild assets
        guild_icon = None
        guild_banner = None
        if guild.icon:
            ext = "gif" if guild.icon.is_animated() else "png"
            guild_icon = f"https://cdn.discordapp.com/icons/{guild.id}/{guild.icon.key}.{ext}?size=512"
        if guild.banner:
            ext = "gif" if guild.banner.is_animated() else "png"
            guild_banner = f"https://cdn.discordapp.com/banners/{guild.id}/{guild.banner.key}.{ext}?size=1024"

        # Update trackers
        member_tracker.update(guild.member_count, online_count)

        # Update moderator statuses
        moderators = get_cached_moderators()
        for mod in moderators:
            member = guild.get_member(int(mod["id"]))
            if member:
                mod["status"] = STATUS_MAP.get(member.status, "offline")
                mod["avatar"] = member.display_avatar.with_size(512).url

        # Update stats store
        stats_store = get_stats_store()
        await stats_store.update(
            guild={
                "name": guild.name,
                "id": guild.id,
                "icon": guild_icon,
                "banner": guild_banner,
                "member_count": guild.member_count,
                "online_count": online_count,
                "boost_level": guild.premium_tier,
                "boost_count": guild.premium_subscription_count or 0,
                "total_messages": 0,
                "chat_active": False,
                "created_at": guild.created_at.isoformat(),
                "moderators": moderators,
            },
            bots={
                "taha": {"online": taha_online},
                "othman": {"online": othman_online},
            },
            developer={
                "status": dev_status,
                "avatar": dev_avatar,
                "banner": dev_banner,
                "decoration": dev_decoration,
                "activities": dev_activities,
            },
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        log.debug("Stats Updated", [
            ("Members", guild.member_count),
            ("Online", online_count),
        ])

    except Exception as e:
        log.error("Stats Collection Failed", [
            ("Error", str(e)[:50]),
        ])


@collect_stats.before_loop
async def before_collect_stats() -> None:
    """Wait for bot to be ready."""
    pass
