"""
TrippixnBot - Embed Footer Utility
==================================

Centralized footer for all embeds.
Avatar is cached and refreshed daily at midnight EST.

Author: حَـــــنَّـــــا
"""

import os
import discord
from typing import Optional

from src.core.logger import log as logger


# Footer text
FOOTER_TEXT = "trippixn.com"

# Cached avatar URL (refreshed daily at midnight EST)
_cached_avatar_url: Optional[str] = None

# Bot reference for refreshing avatar
_bot_ref: Optional[discord.Client] = None


async def _get_developer_avatar(bot: discord.Client) -> Optional[str]:
    """
    Get developer avatar URL for embed footers.

    Args:
        bot: The bot instance

    Returns:
        Avatar URL string or None
    """
    # Fallback URL if bot.user is not available
    default_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"

    # Null check for bot.user
    if bot.user is None:
        return default_avatar

    developer_avatar_url = bot.user.display_avatar.url

    developer_id_str = os.getenv("TRIPPIXN_OWNER_ID")
    if developer_id_str and developer_id_str.isdigit():
        try:
            developer = await bot.fetch_user(int(developer_id_str))
            if developer is not None:
                developer_avatar_url = developer.display_avatar.url
        except (discord.NotFound, discord.HTTPException):
            pass  # Use bot avatar as fallback

    return developer_avatar_url


async def init_footer(bot: discord.Client) -> None:
    """
    Initialize footer with cached avatar.
    Should be called once at bot startup after ready.
    """
    global _bot_ref, _cached_avatar_url
    _bot_ref = bot

    try:
        _cached_avatar_url = await _get_developer_avatar(bot)
        logger.tree("Footer Initialized", [
            ("Text", FOOTER_TEXT),
            ("Avatar Cached", "Yes" if _cached_avatar_url else "No"),
            ("Avatar URL", _cached_avatar_url[:50] + "..." if _cached_avatar_url and len(_cached_avatar_url) > 50 else (_cached_avatar_url or "None")),
            ("Refresh Schedule", "Daily at 00:00 EST"),
        ], emoji="📝")
    except Exception as e:
        logger.error("Footer Init Failed", [
            ("Error", str(e)),
            ("Text", FOOTER_TEXT),
            ("Avatar", "Not cached"),
        ])
        _cached_avatar_url = None


async def refresh_avatar() -> None:
    """
    Refresh the cached avatar URL.
    Called daily at midnight EST by the bot.
    """
    global _cached_avatar_url
    if not _bot_ref:
        logger.warning("Footer Avatar Refresh Skipped", [
            ("Reason", "Bot reference not set"),
        ])
        return

    old_url = _cached_avatar_url
    try:
        _cached_avatar_url = await _get_developer_avatar(_bot_ref)
        changed = old_url != _cached_avatar_url
        logger.tree("Footer Avatar Refreshed", [
            ("Changed", "Yes" if changed else "No"),
            ("New URL", _cached_avatar_url[:50] + "..." if _cached_avatar_url and len(_cached_avatar_url) > 50 else (_cached_avatar_url or "None")),
        ], emoji="🔄")
    except Exception as e:
        logger.error("Footer Avatar Refresh Failed", [
            ("Error", str(e)),
            ("Keeping Old", "Yes" if old_url else "No"),
        ])


def set_footer(embed: discord.Embed, avatar_url: Optional[str] = None) -> discord.Embed:
    """
    Set the standard footer on an embed.

    Args:
        embed: The embed to add footer to
        avatar_url: Optional override avatar URL (uses cached if not provided)

    Returns:
        The embed with footer set
    """
    url = avatar_url if avatar_url is not None else _cached_avatar_url
    embed.set_footer(text=FOOTER_TEXT, icon_url=url)
    return embed


async def set_footer_async(embed: discord.Embed, bot: Optional[discord.Client] = None) -> discord.Embed:
    """
    Set the standard footer on an embed, fetching fresh avatar via API.

    Args:
        embed: The embed to add footer to
        bot: The bot client to fetch avatar from

    Returns:
        The embed with footer set
    """
    client = bot or _bot_ref
    avatar_url = await _get_developer_avatar(client) if client else _cached_avatar_url
    return set_footer(embed, avatar_url)


__all__ = [
    "FOOTER_TEXT",
    "init_footer",
    "refresh_avatar",
    "set_footer",
    "set_footer_async",
]
