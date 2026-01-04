"""
TrippixnBot - Custom Exceptions
==============================

Custom exception classes for better error handling and categorization.

Author: حَـــــنَّـــــا
"""


# =============================================================================
# Base Exceptions
# =============================================================================

class TrippixnError(Exception):
    """Base exception for all TrippixnBot errors."""

    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message


# =============================================================================
# Service Exceptions
# =============================================================================

class ServiceError(TrippixnError):
    """Base exception for service-related errors."""
    pass


class ServiceUnavailableError(ServiceError):
    """Raised when a service is not configured or unavailable."""
    pass


class ServiceTimeoutError(ServiceError):
    """Raised when a service operation times out."""
    pass


class RateLimitError(ServiceError):
    """Raised when rate limited by an external service."""

    def __init__(self, message: str, retry_after: float = None, **kwargs):
        super().__init__(message, kwargs)
        self.retry_after = retry_after


# =============================================================================
# Download Exceptions
# =============================================================================

class DownloadError(TrippixnError):
    """Base exception for download-related errors."""
    pass


class UnsupportedURLError(DownloadError):
    """Raised when URL is not from a supported platform."""
    pass


class ContentNotFoundError(DownloadError):
    """Raised when the content doesn't exist or was deleted."""
    pass


class PrivateContentError(DownloadError):
    """Raised when content requires login or is private."""
    pass


class FileTooLargeError(DownloadError):
    """Raised when file exceeds size limits."""

    def __init__(self, message: str, file_size: int = None, max_size: int = None, **kwargs):
        super().__init__(message, kwargs)
        self.file_size = file_size
        self.max_size = max_size


class CompressionError(DownloadError):
    """Raised when video compression fails."""
    pass


# =============================================================================
# Translation Exceptions
# =============================================================================

class TranslationError(TrippixnError):
    """Base exception for translation-related errors."""
    pass


class UnsupportedLanguageError(TranslationError):
    """Raised when language is not supported."""
    pass


class DetectionFailedError(TranslationError):
    """Raised when language detection fails."""
    pass


# =============================================================================
# API Exceptions
# =============================================================================

class APIError(TrippixnError):
    """Base exception for API-related errors."""

    def __init__(self, message: str, status_code: int = None, **kwargs):
        super().__init__(message, kwargs)
        self.status_code = status_code


class WebhookError(APIError):
    """Raised when webhook delivery fails."""
    pass


class ExternalAPIError(APIError):
    """Raised when external API call fails."""
    pass


# =============================================================================
# Discord Exceptions
# =============================================================================

class DiscordError(TrippixnError):
    """Base exception for Discord-related errors."""
    pass


class MessageTooLongError(DiscordError):
    """Raised when message exceeds Discord limits."""
    pass


class PermissionError(DiscordError):
    """Raised when bot lacks required permissions."""
    pass


class ChannelNotFoundError(DiscordError):
    """Raised when channel doesn't exist or is inaccessible."""
    pass


# =============================================================================
# Configuration Exceptions
# =============================================================================

class ConfigurationError(TrippixnError):
    """Base exception for configuration-related errors."""
    pass


class MissingConfigError(ConfigurationError):
    """Raised when required configuration is missing."""
    pass


class InvalidConfigError(ConfigurationError):
    """Raised when configuration value is invalid."""
    pass
