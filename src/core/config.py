"""
TrippixnBot - Configuration
===========================

Central configuration management.
All values from environment variables - no hardcoded IDs or magic numbers.

Author: حَـــــنَّـــــا
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


# =============================================================================
# Paths
# =============================================================================

ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
LOGS_DIR = ROOT_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


def _get_env_int(key: str, default: int) -> int:
    """Get environment variable as int with default."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# =============================================================================
# Configuration
# =============================================================================

@dataclass(frozen=True)
class Config:
    """Bot configuration - all from environment variables."""

    # Bot settings
    TOKEN: str = os.getenv("TRIPPIXN_BOT_TOKEN", "")
    GUILD_ID: int = _get_env_int("TRIPPIXN_GUILD_ID", 0)
    OWNER_ID: int = _get_env_int("TRIPPIXN_OWNER_ID", 0)

    # Bot IDs to track
    TAHA_BOT_ID: int = _get_env_int("TAHA_BOT_ID", 0)
    OTHMAN_BOT_ID: int = _get_env_int("OTHMAN_BOT_ID", 0)

    # API settings
    API_HOST: str = os.getenv("TRIPPIXN_API_HOST", "0.0.0.0")
    API_PORT: int = _get_env_int("TRIPPIXN_API_PORT", 8081)

    # OpenAI settings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # OpenWeatherMap API
    OPENWEATHER_API_KEY: str = os.getenv("OPENWEATHER_API_KEY", "")

    # Google Custom Search API (for /image command)
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_CX: str = os.getenv("GOOGLE_CX", "")  # Custom Search Engine ID

    # Webhook for ping notifications
    PING_WEBHOOK_URL: str = os.getenv("TRIPPIXN_PING_WEBHOOK_URL", "")

    # Webhook for download logs
    DOWNLOAD_WEBHOOK_URL: str = os.getenv("TRIPPIXN_DOWNLOAD_WEBHOOK_URL", "")

    # Webhook for translation logs
    TRANSLATE_WEBHOOK_URL: str = os.getenv("TRIPPIXN_TRANSLATE_WEBHOOK_URL", "")

    # Webhook for image search logs
    IMAGE_WEBHOOK_URL: str = os.getenv("TRIPPIXN_IMAGE_WEBHOOK_URL", "")

    # Webhook for convert logs
    CONVERT_WEBHOOK_URL: str = os.getenv("TRIPPIXN_CONVERT_WEBHOOK_URL", "")

    # Timing settings (seconds)
    STATS_UPDATE_INTERVAL: int = _get_env_int("TRIPPIXN_STATS_INTERVAL", 60)
    PING_HISTORY_WINDOW: int = _get_env_int("TRIPPIXN_PING_WINDOW", 3600)

    # AutoMod
    AUTOMOD_RULE_NAME: str = os.getenv("TRIPPIXN_AUTOMOD_RULE_NAME", "Block Developer Pings")

    # Role that can ping even when blocking is enabled
    PING_ALLOWED_ROLE_ID: int = 1387043924157272256

    # Moderator role for dashboard display
    MODERATOR_ROLE_ID: int = 1387043924157272256

    # Bump reminder settings
    BUMP_CHANNEL_ID: int = _get_env_int("TRIPPIXN_BUMP_CHANNEL_ID", 0)
    BUMP_ROLE_ID: int = _get_env_int("TRIPPIXN_BUMP_ROLE_ID", 0)


config = Config()
