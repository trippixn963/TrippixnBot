"""
TrippixnBot - Entry Point
=========================

Personal Discord bot for portfolio stats and utilities.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import asyncio
import fcntl
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.bot import TrippixnBot
from src.core import config, log


# =============================================================================
# Constants
# =============================================================================

PROJECT_ROOT = Path(__file__).parent
"""Project root directory."""

BOT_NAME = "TrippixnBot"
"""Bot name for startup logging."""

RUN_ID = uuid.uuid4().hex[:8]
"""Unique identifier for this run (generated once at import time)."""

LOCK_FILE = Path("/tmp/trippixn_bot.lock")
"""Lock file path for single instance enforcement."""


# =============================================================================
# Startup Helpers
# =============================================================================

def _get_git_commit() -> str:
    """Get the current git commit hash (short form)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _get_start_time() -> str:
    """Get formatted start time in EST."""
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S EST")


def _acquire_lock() -> bool:
    """
    Acquire single-instance lock using flock.

    Returns:
        True if lock acquired, False if another instance is running.
    """
    try:
        lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Write PID to lock file for debugging
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()

        # Keep file handle open (lock released when process exits)
        # Store in module-level variable to prevent garbage collection
        global _lock_handle
        _lock_handle = lock_fd

        return True

    except (IOError, OSError):
        return False


async def main() -> None:
    """Start the bot."""
    # Acquire single-instance lock
    if not _acquire_lock():
        log.error("Bot Already Running", [
            ("Lock File", str(LOCK_FILE)),
            ("Action", "Exiting to prevent duplicate instance"),
        ])
        sys.exit(1)

    if not config.BOT_TOKEN:
        log.error("Bot Token Missing", [
            ("Variable", "TRIPPIXN_BOT_TOKEN"),
            ("Status", "Not set in environment"),
        ])
        sys.exit(1)

    log.tree(f"{BOT_NAME} Starting", [
        ("Run ID", RUN_ID),
        ("Started At", _get_start_time()),
        ("Version", _get_git_commit()),
        ("Host", platform.node()),
        ("PID", str(os.getpid())),
        ("Python", platform.python_version()),
        ("Developer", "حَـــــنَّـــــا"),
    ], emoji="🚀")

    bot = TrippixnBot()

    try:
        await bot.start(config.BOT_TOKEN)
    except KeyboardInterrupt:
        log.tree("Keyboard Interrupt", [
            ("Status", "Shutting down gracefully"),
        ], emoji="⌨️")
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
