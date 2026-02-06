"""
Unified Embed Footer Utility
============================

Centralized footer for all embeds across all bots.
Uses server icon (cached and refreshed daily at midnight EST).

Environment Variables:
    FOOTER_TEXT - Footer text displayed on embeds (e.g., "trippixn.com/syria")

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import discord
from typing import Optional

from src.core.logger import logger


# =============================================================================
# Configuration (from environment)
# =============================================================================

def _get_footer_text() -> str:
    """Get footer text from environment variable (bot-prefixed)."""
    bot_name = os.getenv("BOT_NAME", "").upper()
    return os.getenv(f"{bot_name}_FOOTER_TEXT", os.getenv("FOOTER_TEXT", "trippixn.com"))


# =============================================================================
# Module State
# =============================================================================

_cached_icon_url: Optional[str] = None
"""Cached server icon URL (refreshed daily at midnight EST)."""

_bot_ref: Optional[discord.Client] = None
"""Bot reference for refreshing icon."""

_guild_id: Optional[int] = None
"""Guild ID to get icon from."""


# =============================================================================
# Helper Functions
# =============================================================================

def _get_guild_icon(bot: discord.Client) -> Optional[str]:
    """
    Get server icon URL for embed footers.

    Args:
        bot: The bot instance.

    Returns:
        Server icon URL string or None.
    """
    default_icon = "https://cdn.discordapp.com/embed/avatars/0.png"

    if bot.user is None:
        return default_icon

    # Try to get guild icon
    if _guild_id:
        guild = bot.get_guild(_guild_id)
        if guild and guild.icon:
            return guild.icon.url

    # Fallback: try first guild with an icon
    for guild in bot.guilds:
        if guild.icon:
            return guild.icon.url

    # Final fallback: bot avatar
    return bot.user.display_avatar.url if bot.user else default_icon


# =============================================================================
# Initialization
# =============================================================================

async def init_footer(bot: discord.Client, guild_id: Optional[int] = None) -> None:
    """
    Initialize footer with cached server icon.

    Should be called once at bot startup after ready.
    Caches server icon to avoid repeated lookups.

    Args:
        bot: The Discord bot client.
        guild_id: Optional guild ID to get icon from (uses first guild if not provided).
    """
    global _bot_ref, _cached_icon_url, _guild_id
    _bot_ref = bot

    if guild_id:
        _guild_id = guild_id

    footer_text = _get_footer_text()

    try:
        _cached_icon_url = _get_guild_icon(bot)

        # Get guild name for logging
        guild_name = None
        if _guild_id:
            guild = bot.get_guild(_guild_id)
            if guild:
                guild_name = guild.name

        logger.tree("Footer Initialized", [
            ("Text", footer_text),
            ("Guild", guild_name or "Auto-detected"),
            ("Icon Cached", "Yes" if _cached_icon_url else "No"),
        ], emoji="📝")
    except Exception as e:
        logger.error("Footer Init Failed", [
            ("Error", str(e)),
        ])
        _cached_icon_url = None


# =============================================================================
# Icon Refresh
# =============================================================================

async def refresh_avatar() -> None:
    """
    Refresh the cached server icon URL.

    Called daily at midnight EST by the scheduler.
    Logs whether icon changed for debugging.
    """
    global _cached_icon_url
    if not _bot_ref:
        logger.warning("Footer Icon Refresh Skipped", [
            ("Reason", "Bot reference not set"),
        ])
        return

    old_url = _cached_icon_url
    try:
        _cached_icon_url = _get_guild_icon(_bot_ref)
        changed = old_url != _cached_icon_url
        logger.tree("Footer Icon Refreshed", [
            ("Changed", "Yes" if changed else "No"),
        ], emoji="🔄")
    except Exception as e:
        logger.error("Footer Icon Refresh Failed", [
            ("Error", str(e)),
        ])


# =============================================================================
# Footer Setters
# =============================================================================

def set_footer(embed: discord.Embed, icon_url: Optional[str] = None) -> discord.Embed:
    """
    Set the standard footer on an embed.

    Uses cached server icon URL by default.
    Allows override for special cases.

    Args:
        embed: The embed to add footer to.
        icon_url: Optional override icon URL (uses cached if not provided).

    Returns:
        The embed with footer set.
    """
    url = icon_url if icon_url is not None else _cached_icon_url
    embed.set_footer(text=_get_footer_text(), icon_url=url)
    return embed


async def set_footer_async(embed: discord.Embed, bot: Optional[discord.Client] = None) -> discord.Embed:
    """
    Set the standard footer on an embed, fetching fresh icon.

    Args:
        embed: The embed to add footer to.
        bot: The bot client to fetch icon from.

    Returns:
        The embed with footer set.
    """
    client = bot or _bot_ref
    icon_url = _get_guild_icon(client) if client else _cached_icon_url
    return set_footer(embed, icon_url)


def set_game_footer(embed: discord.Embed, stats: dict, user: discord.Member) -> discord.Embed:
    """
    Set footer with player game stats and avatar (for casino/game bots).

    Args:
        embed: The embed to add footer to.
        stats: Dict with 'games' and 'wins' keys.
        user: The player whose stats to display.

    Returns:
        The embed with footer set.
    """
    win_rate = (stats["wins"] / stats["games"] * 100) if stats["games"] > 0 else 0
    embed.set_footer(
        text=f"{stats['games']} games | {win_rate:.0f}% win rate",
        icon_url=user.display_avatar.url if user.display_avatar else None
    )
    return embed


# =============================================================================
# Module Constants
# =============================================================================

FOOTER_TEXT = _get_footer_text()


# =============================================================================
# Module Export
# =============================================================================

__all__ = [
    "FOOTER_TEXT",
    "init_footer",
    "refresh_avatar",
    "set_footer",
    "set_footer_async",
    "set_game_footer",
]
