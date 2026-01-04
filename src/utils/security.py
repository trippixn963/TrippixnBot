"""
TrippixnBot - Security Utilities
================================

Input validation, sanitization, and security utilities.

Author: حَـــــنَّـــــا
"""

import re
import html
import hashlib
from typing import Optional, Set
from urllib.parse import urlparse, parse_qs


# =============================================================================
# URL Validation
# =============================================================================

# Allowed URL schemes
ALLOWED_SCHEMES: Set[str] = {"http", "https"}

# Allowed hosts for downloads
ALLOWED_DOWNLOAD_HOSTS: Set[str] = {
    # Instagram
    "instagram.com",
    "www.instagram.com",
    # Twitter/X
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
    "mobile.twitter.com",
    "mobile.x.com",
    # TikTok
    "tiktok.com",
    "www.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}

# Dangerous URL patterns that could indicate injection
DANGEROUS_URL_PATTERNS = [
    r"[<>\"']",  # HTML/quote injection
    r"\x00",  # Null bytes
    r"javascript:",  # JavaScript protocol
    r"data:",  # Data URLs
    r"file:",  # File protocol
    r"\\\\",  # UNC paths
    r"\.\.\/",  # Path traversal
    r"\.\./",  # Path traversal
]


def validate_url(url: str, allowed_hosts: Optional[Set[str]] = None) -> tuple[bool, Optional[str]]:
    """
    Validate a URL for security.

    Args:
        url: URL to validate
        allowed_hosts: Optional set of allowed hostnames

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "URL is required"

    # Check length
    if len(url) > 2048:
        return False, "URL too long"

    # Check for dangerous patterns
    for pattern in DANGEROUS_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return False, "URL contains invalid characters"

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    # Check scheme
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"Invalid URL scheme: {parsed.scheme}"

    # Check host
    if not parsed.netloc:
        return False, "URL missing host"

    # Extract hostname (without port)
    hostname = parsed.netloc.split(":")[0].lower()

    # Check against allowed hosts if provided
    if allowed_hosts and hostname not in allowed_hosts:
        return False, f"Host not allowed: {hostname}"

    return True, None


def validate_download_url(url: str) -> tuple[bool, Optional[str]]:
    """
    Validate a URL specifically for downloads.

    Args:
        url: URL to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_url(url, ALLOWED_DOWNLOAD_HOSTS)


def sanitize_url_for_logging(url: str) -> str:
    """
    Sanitize a URL for safe logging (remove query params that might contain sensitive data).

    Args:
        url: URL to sanitize

    Returns:
        Sanitized URL safe for logging
    """
    try:
        parsed = urlparse(url)
        # Only keep scheme, host, and path
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return "<invalid-url>"


# =============================================================================
# Input Sanitization
# =============================================================================

# Maximum lengths for various inputs
MAX_TEXT_LENGTH = 4000  # Discord message limit
MAX_USERNAME_LENGTH = 32
MAX_FILENAME_LENGTH = 255
MAX_QUERY_LENGTH = 500


def sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """
    Sanitize text input.

    Args:
        text: Text to sanitize
        max_length: Maximum allowed length

    Returns:
        Sanitized text
    """
    if not text:
        return ""

    # Truncate to max length
    text = text[:max_length]

    # Remove null bytes
    text = text.replace("\x00", "")

    # Normalize whitespace
    text = " ".join(text.split())

    return text


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent path traversal and other issues.

    Args:
        filename: Filename to sanitize

    Returns:
        Safe filename
    """
    if not filename:
        return "unnamed"

    # Remove path separators
    filename = filename.replace("/", "_").replace("\\", "_")

    # Remove null bytes
    filename = filename.replace("\x00", "")

    # Remove other dangerous characters
    filename = re.sub(r'[<>:"|?*]', "_", filename)

    # Remove leading/trailing dots and spaces
    filename = filename.strip(". ")

    # Truncate
    filename = filename[:MAX_FILENAME_LENGTH]

    # Default if empty
    return filename or "unnamed"


def escape_markdown(text: str) -> str:
    """
    Escape Discord markdown characters.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for Discord
    """
    # Characters that need escaping in Discord markdown
    markdown_chars = ["*", "_", "`", "~", "|", ">", "#", "-", "=", "[", "]", "(", ")"]

    for char in markdown_chars:
        text = text.replace(char, f"\\{char}")

    return text


def escape_html(text: str) -> str:
    """
    Escape HTML entities.

    Args:
        text: Text to escape

    Returns:
        HTML-escaped text
    """
    return html.escape(text)


# =============================================================================
# Secrets Protection
# =============================================================================

# Patterns that look like secrets
SECRET_PATTERNS = [
    (r"(token[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_-]{20,})", r"\1***REDACTED***"),
    (r"(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_-]{20,})", r"\1***REDACTED***"),
    (r"(password[\"']?\s*[:=]\s*[\"']?)([^\s\"']+)", r"\1***REDACTED***"),
    (r"(secret[\"']?\s*[:=]\s*[\"']?)([a-zA-Z0-9_-]{20,})", r"\1***REDACTED***"),
    (r"(webhook[s]?/\d+/)([a-zA-Z0-9_-]+)", r"\1***REDACTED***"),  # Discord webhooks
    (r"(Bearer\s+)([a-zA-Z0-9_.-]+)", r"\1***REDACTED***"),  # Bearer tokens
]


def mask_secrets(text: str) -> str:
    """
    Mask potential secrets in text for safe logging.

    Args:
        text: Text that might contain secrets

    Returns:
        Text with secrets masked
    """
    if not text:
        return text

    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def hash_for_logging(value: str) -> str:
    """
    Create a truncated hash of a value for logging (for correlation without exposing the value).

    Args:
        value: Value to hash

    Returns:
        Truncated hash suitable for logging
    """
    if not value:
        return "<empty>"
    return hashlib.sha256(value.encode()).hexdigest()[:8]


# =============================================================================
# Permission Checks
# =============================================================================

def is_owner(user_id: int, owner_id: int) -> bool:
    """Check if user is the bot owner."""
    return user_id == owner_id


def is_admin(member) -> bool:
    """Check if member has admin permissions."""
    if not member:
        return False
    return member.guild_permissions.administrator


def is_moderator(member) -> bool:
    """Check if member has moderation permissions."""
    if not member:
        return False
    perms = member.guild_permissions
    return perms.administrator or perms.manage_messages or perms.kick_members or perms.ban_members
