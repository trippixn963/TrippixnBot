"""
Unified HTTP Session Manager
============================

Shared aiohttp session with connection pooling, retry logic, and rate limiting.

Features:
- Connection pooling for efficient HTTP requests
- Pre-defined timeouts for common use cases
- Exponential backoff retry on failures and rate limits
- Supports both explicit start/stop and lazy initialization

Usage:
    from src.utils.http import http_session, FAST_TIMEOUT

    # At bot startup (setup_hook):
    await http_session.start()

    # Simple request (with default timeout):
    async with http_session.get("https://...") as resp:
        data = await resp.json()

    # With custom timeout:
    async with http_session.get("https://...", timeout=FAST_TIMEOUT) as resp:
        data = await resp.json()

    # With automatic retry on failures/rate limits:
    resp = await http_session.get_with_retry("https://...")
    if resp:
        data = await resp.json()

    # In bot shutdown (close):
    await http_session.stop()

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import aiohttp
from typing import Optional, Callable

from src.core.logger import logger


# =============================================================================
# Pre-defined Timeouts
# =============================================================================

# Default timeout for most requests
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Fast timeout for quick API calls (Lanyard, health checks, etc.)
FAST_TIMEOUT = aiohttp.ClientTimeout(total=5)

# Webhook timeout (fire and forget, don't wait long)
WEBHOOK_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Download timeout (for fetching images/files)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10)


# =============================================================================
# Retry Settings
# =============================================================================

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
MAX_BACKOFF_DELAY = 300.0  # 5 minutes max


# =============================================================================
# HTTP Session Manager
# =============================================================================

class HTTPSessionManager:
    """
    Manages a shared aiohttp ClientSession for the entire application.

    Supports both:
    - Explicit lifecycle (start/stop) for production use
    - Lazy initialization for convenience in development
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._user_agent: str = "DiscordBot/1.0"

    @property
    def session(self) -> aiohttp.ClientSession:
        """
        Get the current session.

        Lazily creates a session if not started explicitly.
        For production, prefer calling start() during setup_hook.
        """
        if self._session is None or self._session.closed:
            # Lazy initialization with basic settings
            self._session = aiohttp.ClientSession(
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": self._user_agent},
            )
            logger.tree("HTTP Session", [
                ("Status", "Created (lazy)"),
            ], emoji="🌐")
        return self._session

    async def start(self, user_agent: Optional[str] = None) -> None:
        """
        Start the HTTP session with optimized settings.

        Call this in bot setup_hook for best performance.

        Args:
            user_agent: Optional custom User-Agent header
        """
        if self._session is not None and not self._session.closed:
            return  # Already started

        if user_agent:
            self._user_agent = user_agent

        # Use connector with connection pooling optimizations
        connector = aiohttp.TCPConnector(
            limit=100,  # Max connections
            limit_per_host=10,  # Max per host
            ttl_dns_cache=300,  # Cache DNS for 5 minutes
            enable_cleanup_closed=True,
        )
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": self._user_agent},
        )
        logger.tree("HTTP Session Manager", [
            ("Status", "Started"),
            ("Pooling", "Enabled"),
        ], emoji="🌐")

    async def stop(self) -> None:
        """Stop the HTTP session. Call this in bot close."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.tree("HTTP Session Manager", [
                ("Status", "Stopped"),
            ], emoji="🔌")

    # Alias for compatibility
    async def close(self) -> None:
        """Alias for stop()."""
        await self.stop()

    def is_running(self) -> bool:
        """Check if session is running."""
        return self._session is not None and not self._session.closed

    # =========================================================================
    # Basic Request Methods
    # =========================================================================

    def get(self, url: str, **kwargs):
        """Perform a GET request. Returns a context manager."""
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        """Perform a POST request. Returns a context manager."""
        return self.session.post(url, **kwargs)

    def put(self, url: str, **kwargs):
        """Perform a PUT request. Returns a context manager."""
        return self.session.put(url, **kwargs)

    def delete(self, url: str, **kwargs):
        """Perform a DELETE request. Returns a context manager."""
        return self.session.delete(url, **kwargs)

    def patch(self, url: str, **kwargs):
        """Perform a PATCH request. Returns a context manager."""
        return self.session.patch(url, **kwargs)

    # =========================================================================
    # Retry Request Methods
    # =========================================================================

    async def get_with_retry(
        self,
        url: str,
        max_retries: int = MAX_RETRIES,
        **kwargs
    ) -> Optional[aiohttp.ClientResponse]:
        """
        GET request with exponential backoff retry on rate limits and errors.

        Args:
            url: URL to fetch
            max_retries: Maximum retry attempts
            **kwargs: Additional arguments passed to session.get()

        Returns:
            Response object or None if all retries failed
        """
        return await self._request_with_retry("GET", url, max_retries, **kwargs)

    async def post_with_retry(
        self,
        url: str,
        max_retries: int = MAX_RETRIES,
        **kwargs
    ) -> Optional[aiohttp.ClientResponse]:
        """
        POST request with exponential backoff retry on rate limits and errors.

        Args:
            url: URL to post to
            max_retries: Maximum retry attempts
            **kwargs: Additional arguments passed to session.post()

        Returns:
            Response object or None if all retries failed
        """
        return await self._request_with_retry("POST", url, max_retries, **kwargs)

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        max_retries: int = MAX_RETRIES,
        **kwargs
    ) -> Optional[aiohttp.ClientResponse]:
        """
        Internal method to perform requests with retry logic.

        Handles:
        - 429 rate limits with Retry-After header
        - Connection errors with exponential backoff
        - Timeout errors
        """
        request_method: Callable = getattr(self.session, method.lower())

        for attempt in range(max_retries):
            try:
                response = await request_method(url, **kwargs)

                if response.status == 429:
                    # Consume response body to prevent resource leak
                    await response.read()

                    # Rate limited - use Retry-After header or exponential backoff
                    retry_after = response.headers.get("Retry-After")
                    delay = RETRY_BASE_DELAY * (2 ** attempt)  # Default fallback
                    if retry_after:
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            pass  # Use default backoff if malformed

                    # Cap the delay to prevent excessive waits
                    delay = min(delay, MAX_BACKOFF_DELAY)

                    logger.tree("HTTP Rate Limited", [
                        ("URL", url[:60] + "..." if len(url) > 60 else url),
                        ("Attempt", f"{attempt + 1}/{max_retries}"),
                        ("Retry After", f"{delay:.1f}s"),
                    ], emoji="⏳")

                    await asyncio.sleep(delay)
                    continue

                return response

            except asyncio.TimeoutError:
                logger.tree("HTTP Timeout", [
                    ("URL", url[:60] + "..." if len(url) > 60 else url),
                    ("Attempt", f"{attempt + 1}/{max_retries}"),
                ], emoji="⏳")
            except aiohttp.ClientError as e:
                logger.tree("HTTP Error", [
                    ("URL", url[:60] + "..." if len(url) > 60 else url),
                    ("Error", str(e)[:50]),
                    ("Attempt", f"{attempt + 1}/{max_retries}"),
                ], emoji="⚠️")

            # Exponential backoff before retry (capped)
            if attempt < max_retries - 1:
                delay = min(RETRY_BASE_DELAY * (2 ** attempt), MAX_BACKOFF_DELAY)
                await asyncio.sleep(delay)

        logger.tree("HTTP Request Failed", [
            ("Method", method),
            ("URL", url[:60] + "..." if len(url) > 60 else url),
            ("Reason", "All retries exhausted"),
        ], emoji="❌")
        return None


# =============================================================================
# Global Instance
# =============================================================================

http_session = HTTPSessionManager()


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Session manager
    "http_session",
    "HTTPSessionManager",
    # Timeouts
    "DEFAULT_TIMEOUT",
    "FAST_TIMEOUT",
    "WEBHOOK_TIMEOUT",
    "DOWNLOAD_TIMEOUT",
    # Retry settings
    "MAX_RETRIES",
    "RETRY_BASE_DELAY",
    "MAX_BACKOFF_DELAY",
]
