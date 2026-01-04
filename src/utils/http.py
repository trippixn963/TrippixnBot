"""
TrippixnBot - HTTP Session Manager
==================================

Shared aiohttp session for efficient connection pooling.

Author: حَـــــنَّـــــا
"""

import aiohttp
from typing import Optional

from src.core import log


# =============================================================================
# Pre-defined Timeouts (for common use cases)
# =============================================================================

# Default timeout for most requests
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Fast timeout for quick API calls (Lanyard, etc.)
FAST_TIMEOUT = aiohttp.ClientTimeout(total=5)

# Webhook timeout (fire and forget, don't wait long)
WEBHOOK_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Download timeout (for fetching images/files)
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)


class HTTPSessionManager:
    """
    Manages a shared aiohttp ClientSession for the entire application.

    Usage:
        # In bot startup (setup_hook):
        await http_session.start()

        # Throughout the app (with default timeout):
        async with http_session.get("https://...") as resp:
            data = await resp.json()

        # With custom timeout:
        async with http_session.get("https://...", timeout=FAST_TIMEOUT) as resp:
            data = await resp.json()

        # In bot shutdown (close):
        await http_session.stop()
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get the current session. Raises if not started."""
        if self._session is None or self._session.closed:
            raise RuntimeError("HTTP session not started. Call http_session.start() first.")
        return self._session

    async def start(self) -> None:
        """Start the HTTP session. Call this in bot setup_hook."""
        if self._session is None or self._session.closed:
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
                headers={"User-Agent": "TrippixnBot/1.0"},
            )
            log.success("HTTP Session Manager started (pooling enabled)")

    async def stop(self) -> None:
        """Stop the HTTP session. Call this in bot close."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            log.success("HTTP Session Manager stopped")

    def get(self, url: str, **kwargs):
        """Perform a GET request. Returns a context manager."""
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        """Perform a POST request. Returns a context manager."""
        return self.session.post(url, **kwargs)

    def is_running(self) -> bool:
        """Check if session is running."""
        return self._session is not None and not self._session.closed


# Global instance
http_session = HTTPSessionManager()
