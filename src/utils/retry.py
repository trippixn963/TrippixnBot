"""
Unified Retry Utilities
=======================

Exponential backoff retry decorators and helpers for handling transient failures.

Features:
- exponential_backoff: Decorator for async functions with configurable retries
- retry: Decorator that handles both sync and async functions
- retry_async: Helper for inline retries
- CircuitBreaker: Circuit breaker pattern for failing services
- Safe Discord helpers: safe_fetch_channel, safe_fetch_message, safe_send, etc.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import random
import time
from functools import wraps
from typing import (
    Any,
    Callable,
    Optional,
    Tuple,
    Type,
    TYPE_CHECKING,
)

import aiohttp
import discord

from src.core.logger import logger

if TYPE_CHECKING:
    pass


# =============================================================================
# Constants
# =============================================================================

# Specific exceptions that should be retried (transient errors)
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    aiohttp.ClientError,
    discord.HTTPException,
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)

# Discord-specific retryable exceptions
DISCORD_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    discord.HTTPException,
    asyncio.TimeoutError,
    ConnectionError,
)

# OpenAI-specific retryable exceptions
OPENAI_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    aiohttp.ClientError,
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)


# =============================================================================
# Exponential Backoff Decorator
# =============================================================================

def exponential_backoff(
    max_retries: int = 3,
    base_delay: float = 10.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that retries async functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 10)
        max_delay: Maximum delay cap in seconds (default: 60)
        exceptions: Exception types to retry on (default: RETRYABLE_EXCEPTIONS)

    Returns:
        Decorated function with retry logic

    Example:
        @exponential_backoff(max_retries=3, base_delay=10)
        async def fetch_data():
            # ... fetching logic ...
            pass

    Formula: delay = min(base_delay * (2 ** attempt), max_delay)
    Example with base_delay=10: 10s -> 20s -> 40s (capped at max_delay)
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} attempts: {e}"
                        )
                        raise

                    # Calculate exponential backoff delay with jitter
                    delay: float = min(base_delay * (2 ** attempt), max_delay)
                    delay += random.uniform(0, delay * 0.1)

                    logger.warning("Retry Attempt Failed", [
                        ("Function", func.__name__),
                        ("Attempt", f"{attempt + 1}/{max_retries}"),
                        ("Error", str(e)),
                    ])
                    logger.info("Retrying", [
                        ("Delay", f"{delay:.1f}s"),
                    ])

                    await asyncio.sleep(delay)

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        return wrapper

    return decorator


# =============================================================================
# Universal Retry Decorator (Sync + Async)
# =============================================================================

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Retry decorator with exponential backoff for both sync and async functions.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        delay: Initial delay between retries in seconds (default: 1.0)
        backoff: Multiplier for delay after each retry (default: 2.0)
        exceptions: Tuple of exception types to catch and retry (default: Exception)
        on_retry: Optional callback called on each retry with (exception, attempt)

    Example:
        @retry(max_attempts=3, delay=1.0, exceptions=(aiohttp.ClientError,))
        async def fetch_data():
            ...

        @retry(max_attempts=5, backoff=1.5)
        def sync_operation():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.warning(f"Retry exhausted after {max_attempts} attempts", [
                            ("Function", func.__name__),
                            ("Error", str(e)),
                        ])
                        raise

                    logger.info(f"Retry attempt {attempt}/{max_attempts}", [
                        ("Function", func.__name__),
                        ("Error", type(e).__name__),
                        ("Next delay", f"{current_delay:.1f}s"),
                    ])

                    if on_retry:
                        on_retry(e, attempt)

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.warning(f"Retry exhausted after {max_attempts} attempts", [
                            ("Function", func.__name__),
                            ("Error", str(e)),
                        ])
                        raise

                    logger.info(f"Retry attempt {attempt}/{max_attempts}", [
                        ("Function", func.__name__),
                        ("Error", type(e).__name__),
                        ("Next delay", f"{current_delay:.1f}s"),
                    ])

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(current_delay)
                    current_delay *= backoff

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# =============================================================================
# Async Retry Helper
# =============================================================================

async def retry_async(
    coro_func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    **kwargs: Any,
) -> Any:
    """
    Retry an async function with exponential backoff.

    Args:
        coro_func: Async function to retry
        *args: Positional arguments to pass to the function
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        backoff: Multiplier for delay (default: 2.0)
        exceptions: Tuple of exception types to retry on
        **kwargs: Keyword arguments to pass to the function

    Returns:
        Result of the async function

    Raises:
        The last exception if all retries fail

    Example:
        result = await retry_async(
            session.get, url,
            max_retries=3,
            base_delay=1.0
        )
    """
    last_exception: Optional[Exception] = None
    current_delay = base_delay

    for attempt in range(max_retries):
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt == max_retries - 1:
                logger.error("All Retries Failed", [
                    ("Attempts", str(max_retries)),
                    ("Error", f"{type(e).__name__}: {str(e)[:50]}"),
                ])
                raise

            delay = min(current_delay, max_delay)
            delay += random.uniform(0, delay * 0.1)

            logger.debug("Retry Async", [
                ("Attempt", f"{attempt + 1}/{max_retries}"),
                ("Error", str(e)[:50]),
                ("Delay", f"{delay:.1f}s"),
            ])
            await asyncio.sleep(delay)
            current_delay *= backoff

    if last_exception:
        raise last_exception
    raise RuntimeError("retry_async failed without exception")


# =============================================================================
# Circuit Breaker Pattern
# =============================================================================

class CircuitBreaker:
    """
    Circuit breaker pattern for failing services.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, requests are rejected immediately
    - HALF_OPEN: Testing if service has recovered

    Prevents cascading failures by failing fast when a service is down.
    After a timeout period, allows a single request through to test recovery.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            name: Name of the service (for logging)
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
            half_open_max_calls: Number of test calls allowed in half-open state
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        """Get current circuit state, checking for recovery timeout."""
        if self._state == self.OPEN:
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = self.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Circuit Half-Open", [
                        ("Service", self.name),
                        ("Testing Recovery", "Yes"),
                    ])
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self.state == self.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (allowing requests)."""
        return self.state == self.CLOSED

    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        state = self.state
        if state == self.CLOSED:
            return True
        if state == self.HALF_OPEN:
            return self._half_open_calls < self.half_open_max_calls
        return False

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            logger.info("Circuit Closed (Recovered)", [
                ("Service", self.name),
            ])
        elif self._state == self.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            logger.warning("Circuit Re-Opened (Recovery Failed)", [
                ("Service", self.name),
                ("Timeout", f"{self.recovery_timeout}s"),
            ])
        elif self._state == self.CLOSED and self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            logger.warning("Circuit Opened", [
                ("Service", self.name),
                ("Failures", str(self._failure_count)),
                ("Threshold", str(self.failure_threshold)),
                ("Timeout", f"{self.recovery_timeout}s"),
            ])

    async def execute(
        self,
        coro_func: Callable[..., Any],
        *args: Any,
        fallback: Optional[Callable[..., Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a coroutine with circuit breaker protection.

        Args:
            coro_func: Async function to execute
            *args: Positional arguments
            fallback: Optional fallback function if circuit is open
            **kwargs: Keyword arguments

        Returns:
            Result of coro_func or fallback

        Raises:
            CircuitOpenError: If circuit is open and no fallback provided
        """
        if not self.can_execute():
            if fallback:
                logger.debug("Circuit Open - Using Fallback", [
                    ("Service", self.name),
                ])
                if asyncio.iscoroutinefunction(fallback):
                    return await fallback(*args, **kwargs)
                return fallback(*args, **kwargs)
            raise CircuitOpenError(f"Circuit breaker '{self.name}' is open")

        if self._state == self.HALF_OPEN:
            self._half_open_calls += 1

        try:
            result = await coro_func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and no fallback is provided."""
    pass


# Global circuit breakers registry
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """
    Get or create a circuit breaker for a service.

    Args:
        name: Service name (e.g., "openai", "news_api")
        failure_threshold: Number of failures before opening
        recovery_timeout: Seconds before testing recovery

    Returns:
        CircuitBreaker instance
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _circuit_breakers[name]


# =============================================================================
# Safe Discord Helpers
# =============================================================================

async def safe_fetch_channel(
    bot: Any,
    channel_id: int,
) -> Optional[discord.abc.GuildChannel]:
    """
    Safely fetch a channel with retry logic.

    Args:
        bot: Bot instance
        channel_id: Channel ID to fetch

    Returns:
        Channel object or None if not found/failed
    """
    if not channel_id:
        return None

    # Try cache first
    channel = bot.get_channel(channel_id)
    if channel:
        return channel

    # Fetch with retry
    try:
        return await retry_async(
            bot.fetch_channel,
            channel_id,
            max_retries=2,
            base_delay=0.5,
            exceptions=DISCORD_RETRYABLE_EXCEPTIONS,
        )
    except (discord.NotFound, discord.Forbidden):
        return None
    except Exception as e:
        logger.error("Channel Fetch Failed", [
            ("Channel ID", str(channel_id)),
            ("Error", str(e)[:50]),
        ])
        return None


async def safe_fetch_message(
    channel: discord.abc.Messageable,
    message_id: int,
) -> Optional[discord.Message]:
    """
    Safely fetch a message with retry logic.

    Args:
        channel: Channel to fetch from
        message_id: Message ID to fetch

    Returns:
        Message object or None if not found/failed
    """
    if not channel or not message_id:
        return None

    try:
        return await retry_async(
            channel.fetch_message,
            message_id,
            max_retries=2,
            base_delay=0.5,
            exceptions=DISCORD_RETRYABLE_EXCEPTIONS,
        )
    except (discord.NotFound, discord.Forbidden):
        return None
    except Exception as e:
        logger.error("Message Fetch Failed", [
            ("Message ID", str(message_id)),
            ("Error", str(e)[:50]),
        ])
        return None


async def safe_send(
    channel: discord.abc.Messageable,
    content: Optional[str] = None,
    **kwargs: Any,
) -> Optional[discord.Message]:
    """
    Safely send a message with retry logic.

    Args:
        channel: Channel to send to
        content: Message content
        **kwargs: Additional arguments (embed, view, etc.)

    Returns:
        Sent message or None on failure
    """
    if not channel:
        return None

    try:
        return await retry_async(
            channel.send,
            content,
            max_retries=2,
            base_delay=0.5,
            exceptions=DISCORD_RETRYABLE_EXCEPTIONS,
            **kwargs,
        )
    except (discord.Forbidden, discord.HTTPException) as e:
        logger.error("Message Send Failed", [
            ("Error", str(e)[:50]),
        ])
        return None


async def safe_edit(
    message: discord.Message,
    **kwargs: Any,
) -> Optional[discord.Message]:
    """
    Safely edit a message with retry logic.

    Args:
        message: Message to edit
        **kwargs: Edit arguments (content, embed, etc.)

    Returns:
        Edited message or None on failure
    """
    if not message:
        return None

    try:
        return await retry_async(
            message.edit,
            max_retries=2,
            base_delay=0.5,
            exceptions=DISCORD_RETRYABLE_EXCEPTIONS,
            **kwargs,
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        logger.error("Message Edit Failed", [
            ("Message ID", str(message.id)),
            ("Error", str(e)[:50]),
        ])
        return None


async def safe_delete(message: discord.Message) -> bool:
    """
    Safely delete a message with retry logic.

    Args:
        message: Message to delete

    Returns:
        True if deleted, False on failure
    """
    if not message:
        return False

    try:
        await retry_async(
            message.delete,
            max_retries=2,
            base_delay=0.5,
            exceptions=DISCORD_RETRYABLE_EXCEPTIONS,
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def safe_add_reaction(
    message: discord.Message,
    emoji: str,
) -> bool:
    """
    Safely add a reaction to a message.

    Args:
        message: Message to react to
        emoji: Emoji to add

    Returns:
        True if added, False on failure
    """
    if not message:
        return False

    try:
        await retry_async(
            message.add_reaction,
            emoji,
            max_retries=2,
            base_delay=0.5,
            exceptions=DISCORD_RETRYABLE_EXCEPTIONS,
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def safe_followup(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    **kwargs: Any,
) -> Optional[discord.Message]:
    """
    Safely send an interaction followup with error handling.

    Handles common issues like:
    - Interaction already responded
    - Interaction expired
    - HTTP errors

    Args:
        interaction: Discord interaction
        content: Message content
        **kwargs: Additional arguments (embed, view, ephemeral, etc.)

    Returns:
        Sent message or None on failure
    """
    if not interaction:
        return None

    try:
        # Check if interaction is still valid
        if interaction.is_expired():
            logger.debug("Interaction Expired - Cannot Send Followup")
            return None

        return await interaction.followup.send(content, **kwargs)
    except discord.NotFound:
        logger.debug("Interaction Not Found - Token Expired")
        return None
    except discord.HTTPException as e:
        # Check for specific error codes
        if e.code == 10062:  # Unknown interaction
            logger.debug("Unknown Interaction - Token Expired")
        elif e.code == 40060:  # Interaction already acknowledged
            logger.debug("Interaction Already Acknowledged")
        else:
            logger.warning("Followup Send Failed", [
                ("Error Code", str(e.code)),
                ("Error", str(e.text)[:50] if e.text else "Unknown"),
            ])
        return None
    except Exception as e:
        logger.error("Followup Send Exception", [
            ("Error", str(e)[:50]),
        ])
        return None


# =============================================================================
# Webhook Alert Helper
# =============================================================================

async def send_webhook_alert_safe(
    bot: Any,
    title: str,
    message: str,
) -> bool:
    """
    Safely send an alert to the bot's status webhook.

    This function checks if the bot has a status_service with alert capability
    and sends the alert. Silently fails if not configured.

    Args:
        bot: Bot instance (must have status_service attribute)
        title: Alert title
        message: Alert message content

    Returns:
        True if sent, False otherwise
    """
    try:
        # Check if bot has status service
        status_service = getattr(bot, 'status_service', None)
        if not status_service:
            return False

        # Check if status service has send_alert method
        send_alert = getattr(status_service, 'send_alert', None)
        if not send_alert:
            return False

        await send_alert(title, message)
        return True
    except Exception as e:
        logger.debug("Webhook Alert Failed", [
            ("Title", title[:30]),
            ("Error", str(e)[:50]),
        ])
        return False


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Decorators
    "exponential_backoff",
    "retry",
    # Helpers
    "retry_async",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitOpenError",
    "get_circuit_breaker",
    # Safe Discord helpers
    "safe_fetch_channel",
    "safe_fetch_message",
    "safe_send",
    "safe_edit",
    "safe_delete",
    "safe_add_reaction",
    "safe_followup",
    # Webhook alert
    "send_webhook_alert_safe",
    # Constants
    "RETRYABLE_EXCEPTIONS",
    "DISCORD_RETRYABLE_EXCEPTIONS",
    "OPENAI_RETRYABLE_EXCEPTIONS",
]
