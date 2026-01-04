"""
TrippixnBot - Utilities
=======================

Shared utility modules.

Author: حَـــــنَّـــــا
"""

from src.utils.http import http_session
from src.utils.webhooks import send_webhook
from src.utils.retry import retry, retry_async
from src.utils.security import (
    validate_url,
    validate_download_url,
    sanitize_url_for_logging,
    sanitize_text,
    sanitize_filename,
    escape_markdown,
    escape_html,
    mask_secrets,
    hash_for_logging,
    is_owner,
    is_admin,
    is_moderator,
)

__all__ = [
    "http_session",
    "send_webhook",
    "retry",
    "retry_async",
    # Security utilities
    "validate_url",
    "validate_download_url",
    "sanitize_url_for_logging",
    "sanitize_text",
    "sanitize_filename",
    "escape_markdown",
    "escape_html",
    "mask_secrets",
    "hash_for_logging",
    "is_owner",
    "is_admin",
    "is_moderator",
]
