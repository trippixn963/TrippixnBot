"""
TrippixnBot - Constants
=======================

All magic numbers, limits, and configuration values.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from zoneinfo import ZoneInfo


# =============================================================================
# Timezone
# =============================================================================

TIMEZONE_EST = ZoneInfo("America/New_York")


# =============================================================================
# Time Constants
# =============================================================================

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
MS_PER_SECOND = 1000


# =============================================================================
# Network & API
# =============================================================================

HEALTH_CHECK_PORT = 8086
HTTP_TIMEOUT = 30.0
WEBHOOK_TIMEOUT = 10.0


# =============================================================================
# AI Service
# =============================================================================

AI_MAX_TOKENS = 500
AI_TEMPERATURE = 0.7
AI_CONTEXT_MESSAGES = 10
AI_CACHE_TTL = 300  # 5 minutes


# =============================================================================
# Message Tracking
# =============================================================================

MESSAGE_CACHE_SIZE = 1000
MESSAGE_CACHE_TTL = 3600  # 1 hour


# =============================================================================
# Member Tracking
# =============================================================================

MEMBER_SYNC_INTERVAL = 300  # 5 minutes
MEMBER_CACHE_SIZE = 500


# =============================================================================
# Discord API Limits
# =============================================================================

DISCORD_MESSAGE_LIMIT = 2000
DISCORD_EMBED_TITLE_LIMIT = 256
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_NAME_LIMIT = 256
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_FOOTER_LIMIT = 2048
DISCORD_EMBED_MAX_FIELDS = 25


# =============================================================================
# Presence
# =============================================================================

PRESENCE_UPDATE_INTERVAL = 60  # 1 minute


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Timezone
    "TIMEZONE_EST",
    # Time
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "MS_PER_SECOND",
    # Network
    "HEALTH_CHECK_PORT",
    "HTTP_TIMEOUT",
    "WEBHOOK_TIMEOUT",
    # AI
    "AI_MAX_TOKENS",
    "AI_TEMPERATURE",
    "AI_CONTEXT_MESSAGES",
    "AI_CACHE_TTL",
    # Message
    "MESSAGE_CACHE_SIZE",
    "MESSAGE_CACHE_TTL",
    # Member
    "MEMBER_SYNC_INTERVAL",
    "MEMBER_CACHE_SIZE",
    # Discord
    "DISCORD_MESSAGE_LIMIT",
    "DISCORD_EMBED_TITLE_LIMIT",
    "DISCORD_EMBED_DESCRIPTION_LIMIT",
    "DISCORD_EMBED_FIELD_NAME_LIMIT",
    "DISCORD_EMBED_FIELD_VALUE_LIMIT",
    "DISCORD_EMBED_FOOTER_LIMIT",
    "DISCORD_EMBED_MAX_FIELDS",
    # Presence
    "PRESENCE_UPDATE_INTERVAL",
]
