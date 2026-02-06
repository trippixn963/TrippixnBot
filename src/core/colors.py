"""
Unified Color Constants
=======================

Shared color definitions for Discord embeds across all bots.

Note: Bot-specific emojis should be defined in each bot's own emojis.py file,
not in this shared module.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import discord


# =============================================================================
# Base Color Values (Hex)
# =============================================================================

# Primary brand colors (Syria Discord)
COLOR_GREEN = 0x1F5E2E      # Syria green
COLOR_GOLD = 0xE6B84A       # Syria gold (primary brand color)
COLOR_RED = 0xB43232        # Syria red

# Discord colors
COLOR_BLURPLE = 0x5865F2    # Discord blurple

# Status colors
COLOR_SUCCESS = 0x43B581    # Green - successful actions
COLOR_ERROR = 0xF04747      # Red - errors and failures
COLOR_WARNING = 0xFAA61A    # Orange - warnings
COLOR_CRITICAL = 0x8B0000   # Dark red - critical errors

# Neutral colors
COLOR_NEUTRAL = 0x95A5A6    # Gray - neutral/cancelled
COLOR_INFO = 0x3498DB       # Blue - informational

# Feature-specific colors
COLOR_BOOST = 0xFF73FA      # Pink - Nitro boosters
COLOR_KARMA = 0xFFD700      # Gold - karma/points
COLOR_LEADERBOARD = 0xF1C40F  # Yellow/Gold - leaderboards
COLOR_NEWS = 0x1ABC9C       # Teal - news posts
COLOR_HOT = 0xFF6B6B        # Coral - hot/trending
COLOR_FEMALE = 0xFF69B4     # Pink - female/feminine
COLOR_MALE = 0x4169E1       # Royal Blue - male/masculine

# Webhook/Status aliases
COLOR_ONLINE = COLOR_SUCCESS
COLOR_OFFLINE = COLOR_ERROR
COLOR_COMMAND = COLOR_BLURPLE


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================

# JawdatBot compatibility
COLOR_PRIMARY = COLOR_GOLD


# =============================================================================
# Discord Embed Colors (discord.Color objects)
# =============================================================================

class EmbedColors:
    """
    Standardized color palette for Discord embeds.

    Use these when you need discord.Color objects instead of hex values.
    """
    # Base colors
    GREEN = discord.Color.from_rgb(31, 94, 46)      # #1F5E2E
    GOLD = discord.Color.from_rgb(230, 184, 74)     # #E6B84A
    RED = discord.Color.from_rgb(180, 50, 50)       # #B43232

    # Status colors
    SUCCESS = discord.Color.from_rgb(67, 181, 129)  # #43B581
    ERROR = discord.Color.from_rgb(240, 71, 71)     # #F04747
    WARNING = discord.Color.from_rgb(250, 166, 26)  # #FAA61A
    NEUTRAL = discord.Color.from_rgb(149, 165, 166) # #95A5A6
    INFO = discord.Color.from_rgb(52, 152, 219)     # #3498DB

    # Action colors (for moderation)
    BAN = RED
    UNBAN = GREEN
    CLOSE = GOLD
    REOPEN = GREEN
    EXPIRED = GOLD

    # Appeal colors
    APPEAL_PENDING = GOLD
    APPEAL_APPROVED = GREEN
    APPEAL_DENIED = RED


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Hex colors
    "COLOR_GREEN",
    "COLOR_GOLD",
    "COLOR_RED",
    "COLOR_BLURPLE",
    "COLOR_SUCCESS",
    "COLOR_ERROR",
    "COLOR_WARNING",
    "COLOR_CRITICAL",
    "COLOR_NEUTRAL",
    "COLOR_INFO",
    "COLOR_BOOST",
    "COLOR_KARMA",
    "COLOR_LEADERBOARD",
    "COLOR_NEWS",
    "COLOR_HOT",
    "COLOR_FEMALE",
    "COLOR_MALE",
    "COLOR_ONLINE",
    "COLOR_OFFLINE",
    "COLOR_COMMAND",
    "COLOR_PRIMARY",
    # Discord.Color objects
    "EmbedColors",
]
