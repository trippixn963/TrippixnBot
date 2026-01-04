"""
TrippixnBot - Core Module
=========================

Author: حَـــــنَّـــــا
"""

from src.core.config import config, DATA_DIR, LOGS_DIR, ROOT_DIR
from src.core.logger import log
from src.core.exceptions import (
    TrippixnError,
    ServiceError,
    ServiceUnavailableError,
    ServiceTimeoutError,
    RateLimitError,
    DownloadError,
    TranslationError,
    APIError,
    DiscordError,
    ConfigurationError,
)

__all__ = [
    "config",
    "log",
    "DATA_DIR",
    "LOGS_DIR",
    "ROOT_DIR",
    # Exceptions
    "TrippixnError",
    "ServiceError",
    "ServiceUnavailableError",
    "ServiceTimeoutError",
    "RateLimitError",
    "DownloadError",
    "TranslationError",
    "APIError",
    "DiscordError",
    "ConfigurationError",
]
