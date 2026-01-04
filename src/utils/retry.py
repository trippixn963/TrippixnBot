"""
TrippixnBot - Retry Utility
===========================

Retry decorator with exponential backoff for handling transient failures.

Author: حَـــــنَّـــــا
"""

import asyncio
import functools
from typing import Type, Tuple, Callable, Any, Optional

from src.core import log


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    Retry decorator with exponential backoff.

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
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        log.warning(f"Retry exhausted after {max_attempts} attempts", [
                            ("Function", func.__name__),
                            ("Error", str(e)),
                        ])
                        raise

                    log.info(f"Retry attempt {attempt}/{max_attempts}", [
                        ("Function", func.__name__),
                        ("Error", type(e).__name__),
                        ("Next delay", f"{current_delay:.1f}s"),
                    ])

                    if on_retry:
                        on_retry(e, attempt)

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            import time
            last_exception = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        log.warning(f"Retry exhausted after {max_attempts} attempts", [
                            ("Function", func.__name__),
                            ("Error", str(e)),
                        ])
                        raise

                    log.info(f"Retry attempt {attempt}/{max_attempts}", [
                        ("Function", func.__name__),
                        ("Error", type(e).__name__),
                        ("Next delay", f"{current_delay:.1f}s"),
                    ])

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


async def retry_async(
    coro_func: Callable,
    *args,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    **kwargs,
) -> Any:
    """
    Retry an async function call with exponential backoff.

    Args:
        coro_func: Async function to call
        *args: Positional arguments for the function
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exception types to catch and retry
        **kwargs: Keyword arguments for the function

    Returns:
        Result of the function call

    Example:
        result = await retry_async(
            fetch_data,
            url,
            max_attempts=3,
            exceptions=(aiohttp.ClientError,)
        )
    """
    last_exception = None
    current_delay = delay

    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as e:
            last_exception = e

            if attempt == max_attempts:
                log.warning(f"Retry exhausted after {max_attempts} attempts", [
                    ("Function", coro_func.__name__),
                    ("Error", str(e)),
                ])
                raise

            log.info(f"Retry attempt {attempt}/{max_attempts}", [
                ("Function", coro_func.__name__),
                ("Error", type(e).__name__),
                ("Next delay", f"{current_delay:.1f}s"),
            ])

            await asyncio.sleep(current_delay)
            current_delay *= backoff

    raise last_exception
