"""
TrippixnBot - Ready Handler
===========================

Handles bot ready event and stats collection.

Author: حَـــــنَّـــــا
"""

import asyncio
import discord
import aiohttp
from discord.ext import tasks
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from src.core import config, log
from src.services import stats_store, message_counter, member_tracker
from src.utils.http import http_session


# =============================================================================
# Moderator Cache (fetched daily at midnight EST)
# =============================================================================

# Cached moderator data with banners/avatars
_moderator_cache: List[Dict[str, Any]] = []
_moderator_cache_updated: Optional[datetime] = None

# EST timezone
EST = ZoneInfo("America/New_York")


async def fetch_moderator_data(bot: discord.Client) -> List[Dict[str, Any]]:
    """Fetch moderator data including banners (expensive API calls)."""
    global _moderator_cache, _moderator_cache_updated

    guild = bot.get_guild(config.GUILD_ID)
    if not guild:
        return []

    moderators = []
    mod_role = guild.get_role(config.MODERATOR_ROLE_ID)
    if not mod_role:
        return []

    # Sort members by their top role position (higher position = higher in hierarchy)
    sorted_members = sorted(
        [m for m in mod_role.members if not m.bot],
        key=lambda m: m.top_role.position,
        reverse=True
    )

    for member in sorted_members:
        avatar_url = member.display_avatar.with_size(512).url

        # Get member's status
        member_status = STATUS_MAP.get(member.status, "offline")

        # Get top role color (excluding @everyone)
        top_role = member.top_role
        role_color = None
        if top_role and top_role.color.value != 0:
            role_color = f"#{top_role.color.value:06x}"

        # Get member's roles (excluding @everyone), sorted by position (highest first)
        member_roles = [
            {"name": r.name, "color": f"#{r.color.value:06x}" if r.color.value != 0 else None}
            for r in sorted(member.roles[1:], key=lambda r: r.position, reverse=True)
            if not r.is_default()
        ][:5]  # Limit to top 5 roles

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

        # Fetch banner (requires API call for each user)
        try:
            user = await bot.fetch_user(member.id)
            if user.banner:
                banner_url = user.banner.with_size(512).url
                mod_data["banner"] = banner_url
            if user.accent_color is not None and user.accent_color.value != 0:
                mod_data["accent_color"] = f"#{user.accent_color.value:06x}"
        except Exception as e:
            log.warning(f"Banner fetch failed for {member.display_name}: {e}")

        moderators.append(mod_data)

    # Update cache
    _moderator_cache = moderators
    _moderator_cache_updated = datetime.now(EST)

    mods_with_banners = [m["display_name"] for m in moderators if m.get("banner")]
    log.tree("Moderator Cache Updated", [
        ("Total Mods", len(moderators)),
        ("With Banners", len(mods_with_banners)),
        ("Updated At", _moderator_cache_updated.strftime("%I:%M %p %Z")),
    ], emoji="👥")

    return moderators


def get_cached_moderators() -> List[Dict[str, Any]]:
    """Get cached moderator data (updates status only, not banners)."""
    return _moderator_cache.copy()


async def _wait_until_midnight_est() -> None:
    """Wait until the next midnight EST."""
    now = datetime.now(EST)
    # Next midnight
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=EST)
    wait_seconds = (midnight - now).total_seconds()

    log.info(f"Next moderator refresh in {wait_seconds / 3600:.1f} hours (midnight EST)")
    await asyncio.sleep(wait_seconds)


@tasks.loop(hours=24)
async def refresh_moderator_cache(bot: discord.Client) -> None:
    """Refresh moderator cache daily at midnight EST."""
    await fetch_moderator_data(bot)

    # Guild protection check
    try:
        await bot._leave_unauthorized_guilds()
    except Exception as e:
        log.warning("Guild Protection Check Failed", [
            ("Error", str(e)[:50]),
        ])


@refresh_moderator_cache.before_loop
async def before_refresh_moderator_cache() -> None:
    """Wait until midnight EST before starting the daily loop."""
    await _wait_until_midnight_est()


# =============================================================================
# Module-Level Constants (for performance)
# =============================================================================

# Status mapping - created once at module load instead of every stats update
STATUS_MAP = {
    discord.Status.online: "online",
    discord.Status.idle: "idle",
    discord.Status.dnd: "dnd",
    discord.Status.offline: "offline",
}

# =============================================================================
# Developer Presence Cache (for large guilds)
# =============================================================================

# Cache developer's activities since Discord doesn't send full presence on GUILD_CREATE for large guilds
_dev_presence_cache = {
    "status": "offline",
    "activities": [],
}


def get_dev_status() -> str:
    """Get the developer's current status (online, idle, dnd, offline)."""
    return _dev_presence_cache["status"]


def is_dev_dnd() -> bool:
    """Check if developer is in Do Not Disturb mode."""
    return _dev_presence_cache["status"] == "dnd"


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

# Statuses that should block pings (DND and offline/invisible)
BLOCKING_STATUSES = {"dnd", "offline"}


def _should_block_pings(status: str) -> bool:
    """Check if the given status should block pings."""
    return status in BLOCKING_STATUSES


async def on_presence_update(bot: discord.Client, before: discord.Member, after: discord.Member) -> None:
    """Handle presence updates - cache developer's activities and toggle AutoMod."""
    global _dev_presence_cache

    if after.id != config.OWNER_ID:
        return

    # Get previous and new status
    old_status = _dev_presence_cache["status"]
    new_status = STATUS_MAP.get(after.status, "offline")

    # Update cache with latest presence data
    _dev_presence_cache["status"] = new_status
    _dev_presence_cache["activities"] = _parse_activities(after.activities)

    log.tree("Developer Presence Updated", [
        ("Status", new_status),
        ("Activities", len(_dev_presence_cache["activities"])),
    ], emoji="👤")

    # Toggle AutoMod rule if blocking status changed
    was_blocking = _should_block_pings(old_status)
    is_blocking = _should_block_pings(new_status)

    if was_blocking != is_blocking:
        await toggle_automod_rule(bot, enabled=is_blocking)


# =============================================================================
# AutoMod Rule Management (DND-based)
# =============================================================================

# Cache the AutoMod rule ID for toggling
_automod_rule_id: int | None = None



async def _find_automod_rule(guild: discord.Guild) -> discord.AutoModRule | None:
    """Find the developer ping blocking AutoMod rule."""
    global _automod_rule_id

    try:
        rules = await guild.fetch_automod_rules()
        for rule in rules:
            if rule.name == config.AUTOMOD_RULE_NAME:
                _automod_rule_id = rule.id
                return rule
    except Exception as e:
        log.error("Failed to fetch AutoMod rules", [
            ("Error", str(e)),
        ])
    return None


async def _send_automod_toggle_webhook(enabled: bool, status: str) -> None:
    """Send webhook notification when AutoMod rule is toggled."""
    if not config.PING_WEBHOOK_URL:
        return

    try:
        color = 0xFF0000 if enabled else 0x00FF00  # Red when blocking, green when allowing
        title = "🛡️ Ping Blocking Enabled" if enabled else "✅ Ping Blocking Disabled"
        description = (
            f"Developer is **{status}** - pings are now **{'blocked' if enabled else 'allowed'}**"
        )

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": [
                {
                    "name": "Status",
                    "value": status.upper(),
                    "inline": True,
                },
                {
                    "name": "Blocking",
                    "value": "Yes" if enabled else "No",
                    "inline": True,
                },
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "TrippixnBot AutoMod"},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(config.PING_WEBHOOK_URL, json={"embeds": [embed]}) as resp:
                if resp.status in (200, 204):
                    log.info("AutoMod toggle webhook sent")
                else:
                    log.warning(f"AutoMod webhook returned status {resp.status}")

    except Exception as e:
        log.error("Failed to send AutoMod webhook", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])


async def toggle_automod_rule(bot: discord.Client, enabled: bool, is_startup: bool = False) -> None:
    """Enable or disable the AutoMod rule based on availability status."""
    try:
        guild = bot.get_guild(config.GUILD_ID)
        if not guild:
            log.warning("Guild not found - cannot toggle AutoMod rule")
            return

        rule = await _find_automod_rule(guild)
        if not rule:
            log.warning("AutoMod rule not found - cannot toggle")
            return

        # Get the allowed role
        allowed_role = guild.get_role(config.PING_ALLOWED_ROLE_ID)
        exempt_roles = [allowed_role] if allowed_role else []

        # Check if we need to update
        current_exempt_ids = {r.id for r in rule.exempt_roles} if rule.exempt_roles else set()
        new_exempt_ids = {config.PING_ALLOWED_ROLE_ID} if allowed_role else set()

        needs_update = rule.enabled != enabled or current_exempt_ids != new_exempt_ids

        if not needs_update:
            log.info(f"AutoMod rule already in correct state (enabled={enabled})")
            return

        await rule.edit(
            enabled=enabled,
            exempt_roles=exempt_roles,
            reason=f"Developer {'unavailable' if enabled else 'available'}"
        )

        # Get current status for logging
        current_status = _dev_presence_cache.get("status", "unknown")

        log.tree("AutoMod Rule Toggled", [
            ("Status", "Enabled" if enabled else "Disabled"),
            ("Developer Status", current_status),
            ("Reason", "Developer unavailable" if enabled else "Developer available"),
            ("Allowed Role", allowed_role.name if allowed_role else "Not found"),
            ("Startup Sync", "Yes" if is_startup else "No"),
        ], emoji="🛡️")

        # Send webhook notification (skip on startup to avoid spam on restarts)
        if not is_startup:
            await _send_automod_toggle_webhook(
                enabled=enabled,
                status=current_status,
            )

    except discord.Forbidden:
        log.error("No permission to edit AutoMod rule")
    except Exception as e:
        log.error("Failed to toggle AutoMod rule", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])


# =============================================================================
# Bot Profile Sync
# =============================================================================

async def _sync_bot_profile(bot: discord.Client) -> None:
    """Sync bot's avatar and banner from developer's profile."""
    try:
        # Fetch developer's full user object
        dev_user = await bot.fetch_user(config.OWNER_ID)

        avatar_bytes = None
        banner_bytes = None

        # Fetch avatar
        if dev_user.avatar:
            avatar_url = dev_user.avatar.with_size(512).url
            async with http_session.get(avatar_url) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()

        # Fetch banner
        if dev_user.banner:
            banner_url = dev_user.banner.with_size(1024).url
            async with http_session.get(banner_url) as resp:
                if resp.status == 200:
                    banner_bytes = await resp.read()

        # Update bot profile
        if avatar_bytes or banner_bytes:
            await bot.user.edit(
                avatar=avatar_bytes,
                banner=banner_bytes,
            )
            log.tree("Bot Profile Synced", [
                ("Avatar", "✅" if avatar_bytes else "❌"),
                ("Banner", "✅" if banner_bytes else "❌"),
            ], emoji="🔄")

    except discord.HTTPException as e:
        # Rate limited or other API error - this is fine, profile is already set
        if e.status != 429:
            log.warning(f"Could not sync bot profile: {e}")
    except Exception as e:
        log.warning(f"Could not sync bot profile: {e}")


# =============================================================================
# Ready Handler
# =============================================================================

async def on_ready(bot: discord.Client) -> None:
    """Handle bot ready event."""
    # Set invisible status (bot appears offline)
    await bot.change_presence(status=discord.Status.invisible)

    # Use startup_banner for nice formatted output
    log.startup_banner(
        bot_name="TrippixnBot",
        bot_id=bot.user.id,
        guilds=len(bot.guilds),
        latency=bot.latency * 1000,
    )

    # Sync bot profile from developer
    await _sync_bot_profile(bot)

    # Sync AutoMod rule state based on developer's current status
    guild = bot.get_guild(config.GUILD_ID)
    if guild:
        dev_member = guild.get_member(config.OWNER_ID)
        if dev_member:
            status = STATUS_MAP.get(dev_member.status, "offline")
            _dev_presence_cache["status"] = status
            should_block = _should_block_pings(status)

            allowed_role = guild.get_role(config.PING_ALLOWED_ROLE_ID)
            log.tree("Startup AutoMod Sync", [
                ("Developer Status", status),
                ("Should Block Pings", "Yes" if should_block else "No"),
                ("Allowed Role", allowed_role.name if allowed_role else "Not found"),
            ], emoji="🔄")

            await toggle_automod_rule(bot, enabled=should_block, is_startup=True)
        else:
            log.warning(f"Developer member not found in guild (ID: {config.OWNER_ID})")
    else:
        log.warning(f"Guild not found (ID: {config.GUILD_ID})")

    # Start message counter
    await message_counter.start()

    # Start member tracker with initial count
    if guild:
        await member_tracker.start(guild.member_count)

    # Fetch initial moderator data (banners, avatars)
    await fetch_moderator_data(bot)

    # Start daily moderator cache refresh (at midnight EST)
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
    """Collect and update server stats."""
    global _dev_presence_cache

    try:
        guild = bot.get_guild(config.GUILD_ID)
        if not guild:
            log.warning(f"Guild {config.GUILD_ID} not found")
            return

        # Count online members
        online_count = sum(
            1 for m in guild.members
            if m.status != discord.Status.offline and not m.bot
        )

        # Check bot statuses
        taha_member = guild.get_member(config.TAHA_BOT_ID)
        othman_member = guild.get_member(config.OTHMAN_BOT_ID)

        taha_online = (
            taha_member is not None
            and taha_member.status != discord.Status.offline
        )
        othman_online = (
            othman_member is not None
            and othman_member.status != discord.Status.offline
        )

        # Check developer status, avatar, banner, decoration, and activities
        dev_member = guild.get_member(config.OWNER_ID)
        dev_status = "offline"
        dev_avatar = None
        dev_banner = None
        dev_decoration = None
        dev_activities = []

        if dev_member:
            dev_status = STATUS_MAP.get(dev_member.status, "offline")
            dev_avatar = dev_member.display_avatar.with_size(512).url

            if dev_member.avatar_decoration:
                dev_decoration = dev_member.avatar_decoration.url

            # Fetch full user object to get banner (not available on Member)
            try:
                dev_user = await bot.fetch_user(config.OWNER_ID)
                if dev_user.banner:
                    dev_banner = dev_user.banner.with_size(1024).url
            except Exception:
                pass  # Banner fetch failed, continue without it

            # Try to get activities from member first, fall back to cache
            if dev_member.activities:
                dev_activities = _parse_activities(dev_member.activities)
                # Update cache too
                _dev_presence_cache["status"] = dev_status
                _dev_presence_cache["activities"] = dev_activities
            else:
                # Use cached activities from presence updates
                dev_activities = _dev_presence_cache["activities"]

        # Build guild icon and banner URLs
        guild_icon = None
        guild_banner = None
        if guild.icon:
            ext = "gif" if guild.icon.is_animated() else "png"
            guild_icon = f"https://cdn.discordapp.com/icons/{guild.id}/{guild.icon.key}.{ext}?size=512"
        if guild.banner:
            ext = "gif" if guild.banner.is_animated() else "png"
            guild_banner = f"https://cdn.discordapp.com/banners/{guild.id}/{guild.banner.key}.{ext}?size=1024"

        # Update member tracker with current count
        member_tracker.update_count(guild.member_count)

        # Get moderators from cache (banners fetched daily at midnight EST)
        # Only update their current status
        moderators = get_cached_moderators()
        for mod in moderators:
            member = guild.get_member(int(mod["id"]))
            if member:
                mod["status"] = STATUS_MAP.get(member.status, "offline")
                mod["avatar"] = member.display_avatar.with_size(512).url  # Avatar can change

        # Update stats store
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
                "messages_this_week": message_counter.get_count(),
                "chat_active": message_counter.is_active(),
                "created_at": guild.created_at.isoformat(),
                "members_gained_this_week": member_tracker.get_growth(),
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

        log.tree_section("Stats Updated", {
            "Guild": [
                ("Members", guild.member_count),
                ("Online", online_count),
            ],
            "Bots": [
                ("Taha", "✅" if taha_online else "❌"),
                ("Othman", "✅" if othman_online else "❌"),
            ],
            "Developer": [
                ("Status", dev_status),
                ("Banner", "✅" if dev_banner else "❌"),
                ("Activities", len(dev_activities)),
            ],
        }, emoji="📊")

    except Exception as e:
        log.error("Failed to collect stats", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])


@collect_stats.before_loop
async def before_collect_stats() -> None:
    """Wait for bot to be ready before starting stats collection."""
    pass
