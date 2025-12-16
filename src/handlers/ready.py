"""
TrippixnBot - Ready Handler
===========================

Handles bot ready event and stats collection.

Author: حَـــــنَّـــــا
"""

import discord
from discord.ext import tasks
from datetime import datetime, timezone
from typing import Optional
import aiohttp

from src.core import config, log
from src.services import stats_store


# =============================================================================
# IDs from config (no hardcoded values)
# =============================================================================

# All IDs now come from config which reads from environment variables

# =============================================================================
# Developer Presence Cache (for large guilds)
# =============================================================================

# Cache developer's activities since Discord doesn't send full presence on GUILD_CREATE for large guilds
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

async def on_presence_update(before: discord.Member, after: discord.Member) -> None:
    """Handle presence updates - cache developer's activities."""
    global _dev_presence_cache

    if after.id != config.OWNER_ID:
        return

    # Update cache with latest presence data
    status_map = {
        discord.Status.online: "online",
        discord.Status.idle: "idle",
        discord.Status.dnd: "dnd",
        discord.Status.offline: "offline",
    }

    _dev_presence_cache["status"] = status_map.get(after.status, "offline")
    _dev_presence_cache["activities"] = _parse_activities(after.activities)

    log.tree("Developer Presence Updated", [
        ("Status", _dev_presence_cache["status"]),
        ("Activities", len(_dev_presence_cache["activities"])),
    ], emoji="👤")


# =============================================================================
# AutoMod Setup - Block Developer Pings
# =============================================================================

async def _setup_automod(bot: discord.Client) -> None:
    """Setup AutoMod rule to block pings to the developer."""
    try:
        guild = bot.get_guild(config.GUILD_ID)
        if not guild:
            log.warning("Guild not found for AutoMod setup")
            return

        # Check if rule already exists
        existing_rules = await guild.fetch_automod_rules()
        for rule in existing_rules:
            if rule.name == config.AUTOMOD_RULE_NAME:
                log.tree("AutoMod Rule Exists", [
                    ("Name", config.AUTOMOD_RULE_NAME),
                    ("Status", "Active"),
                ], emoji="🛡️")
                return

        # Create AutoMod rule to block developer mentions
        # Block both <@ID> and <@!ID> formats
        trigger = discord.AutoModTrigger(
            type=discord.AutoModRuleTriggerType.keyword,
            keyword_filter=[
                f"<@{config.OWNER_ID}>",
                f"<@!{config.OWNER_ID}>",
            ],
        )

        # Block the message
        actions = [
            discord.AutoModRuleAction(
                type=discord.AutoModRuleActionType.block_message,
                custom_message="You cannot ping the developer directly.",
            ),
        ]

        # Exempt the developer from this rule
        exempt_members = [discord.Object(id=config.OWNER_ID)]

        await guild.create_automod_rule(
            name=config.AUTOMOD_RULE_NAME,
            event_type=discord.AutoModRuleEventType.message_send,
            trigger=trigger,
            actions=actions,
            enabled=True,
            exempt_roles=[],
            exempt_channels=[],
            reason="Block pings to developer",
        )

        log.tree("AutoMod Rule Created", [
            ("Name", config.AUTOMOD_RULE_NAME),
            ("Blocked", f"<@{config.OWNER_ID}>"),
            ("Status", "Active"),
        ], emoji="🛡️")

    except discord.Forbidden:
        log.warning("Missing permissions to manage AutoMod rules")
    except Exception as e:
        log.error("AutoMod Setup Failed", [
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

        async with aiohttp.ClientSession() as session:
            # Fetch avatar
            if dev_user.avatar:
                avatar_url = dev_user.avatar.with_size(512).url
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()

            # Fetch banner
            if dev_user.banner:
                banner_url = dev_user.banner.with_size(1024).url
                async with session.get(banner_url) as resp:
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
    # Set custom status
    activity = discord.CustomActivity(name="🌐 trippixn.com")
    await bot.change_presence(status=discord.Status.dnd, activity=activity)

    # Use startup_tree for nice formatted output
    log.startup_tree(
        bot_name=str(bot.user),
        bot_id=bot.user.id,
        guilds=len(bot.guilds),
        latency=bot.latency * 1000,
        extra=[
            ("Status", "🌐 trippixn.com"),
        ]
    )

    # Setup AutoMod to block developer pings
    await _setup_automod(bot)

    # Sync bot profile from developer
    await _sync_bot_profile(bot)

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
            status_map = {
                discord.Status.online: "online",
                discord.Status.idle: "idle",
                discord.Status.dnd: "dnd",
                discord.Status.offline: "offline",
            }
            dev_status = status_map.get(dev_member.status, "offline")
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

        # Update stats store
        await stats_store.update(
            guild={
                "name": guild.name,
                "id": guild.id,
                "member_count": guild.member_count,
                "online_count": online_count,
                "boost_level": guild.premium_tier,
                "boost_count": guild.premium_subscription_count or 0,
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
