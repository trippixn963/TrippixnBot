"""
Unified Tree Logger
===================

Custom logging system with tree-style formatting and EST timezone support.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST/EDT timezone timestamp formatting (auto-adjusts)
- Tree-style log formatting for structured data
- Nested tree support for hierarchical data
- Console and file output simultaneously
- Daily log folders with separate log and error files
- Automatic cleanup of old logs (7+ days)
- Live logs streaming to Discord webhook in tree format
- Separate error webhook for error-only logs
- Persistent aiohttp session for efficient webhook delivery
- Proper session cleanup on shutdown

Log Structure:
    logs/
    ├── 2025-12-06/
    │   ├── {BOT_NAME}-2025-12-06.log
    │   └── {BOT_NAME}-Errors-2025-12-06.log
    └── ...

Environment Variables:
    BOT_NAME          - Name for log files and webhook usernames (default: Bot)
    LOGS_WEBHOOK_URL  - Discord webhook URL for live logs
    ERROR_WEBHOOK_URL - Discord webhook URL for error-only logs
    DEBUG             - Enable debug logging (1/true/yes)

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import re
import shutil
import uuid
import traceback
import asyncio
import aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

# Timezone for timestamps
TIMEZONE = ZoneInfo("America/New_York")

# Log retention period in days
LOG_RETENTION_DAYS = 7

# Default bot name (can be overridden at runtime via env var)
_DEFAULT_BOT_NAME = "Bot"


def _get_bot_name() -> str:
    """Get bot name from env var at runtime (not import time)."""
    return os.getenv("BOT_NAME", _DEFAULT_BOT_NAME)


# Regex to match emojis (for stripping from file logs)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended
    "\U00002300-\U000023FF"  # misc technical
    "]+",
    flags=re.UNICODE
)


# =============================================================================
# Tree Symbols
# =============================================================================

class TreeSymbols:
    """Box-drawing characters for tree formatting."""
    BRANCH = "├─"      # Middle item connector
    LAST = "└─"        # Last item connector
    PIPE = "│ "        # Vertical continuation
    SPACE = "  "       # Empty space for alignment


# =============================================================================
# Logging Emoji Constants
# =============================================================================
# Standardized emojis for tree logger output - shared across all bots

LOG_EMOJI_SUCCESS = "✅"
LOG_EMOJI_ERROR = "❌"
LOG_EMOJI_WARNING = "⚠️"
LOG_EMOJI_INFO = "ℹ️"
LOG_EMOJI_DEBUG = "🔍"
LOG_EMOJI_CRITICAL = "🚨"
LOG_EMOJI_EXCEPTION = "💥"

# Moderation actions
LOG_EMOJI_BAN = "🔨"
LOG_EMOJI_MUTE = "🔇"
LOG_EMOJI_WARN = "⚠️"
LOG_EMOJI_KICK = "👢"
LOG_EMOJI_LOCK = "🔒"
LOG_EMOJI_UNLOCK = "🔓"

# System/Service
LOG_EMOJI_TICKET = "🎫"
LOG_EMOJI_APPEAL = "📨"
LOG_EMOJI_DATABASE = "🗄️"
LOG_EMOJI_API = "🌐"
LOG_EMOJI_CACHE = "💾"
LOG_EMOJI_SECURITY = "🛡️"
LOG_EMOJI_USER = "👤"
LOG_EMOJI_STARTUP = "🚀"
LOG_EMOJI_SHUTDOWN = "🛑"
LOG_EMOJI_CASE = "📋"
LOG_EMOJI_DM = "📨"
LOG_EMOJI_VOICE = "🔊"
LOG_EMOJI_BOOSTER = "💎"
LOG_EMOJI_COOLDOWN = "⏳"
LOG_EMOJI_BLOCKED = "🚫"


# =============================================================================
# Logger
# =============================================================================

class Logger:
    """Custom logger with tree-style formatting and webhook streaming."""

    # Error emojis that should route to error webhook
    ERROR_EMOJIS = {"❌", "⚠️", "🚨", "💥"}

    def __init__(self) -> None:
        """Initialize the logger with unique run ID and daily log folder rotation."""
        # Unique run ID for this session
        self.run_id: str = str(uuid.uuid4())[:8]

        # Track start time for uptime calculation
        self._start_time: datetime = datetime.now(TIMEZONE)

        # Track last log type for spacing between trees
        self._last_was_tree: bool = False

        # Live logs Discord webhook streaming (from env var with bot prefix)
        bot_name = os.getenv("BOT_NAME", "").upper()
        self._live_logs_webhook_url: str = os.getenv(f"{bot_name}_LOGS_WEBHOOK_URL", "")
        self._live_logs_enabled: bool = bool(self._live_logs_webhook_url)

        # Error webhook (from env var with bot prefix)
        self._error_webhook_url: str = os.getenv(f"{bot_name}_ERROR_WEBHOOK_URL", "")

        # Persistent aiohttp session for webhooks (lazy initialized)
        self._webhook_session: Optional[aiohttp.ClientSession] = None
        self._session_lock: Optional[asyncio.Lock] = None  # Lazy init to avoid event loop issues

        # Base logs directory
        self.logs_base_dir = Path(__file__).parent.parent.parent / "logs"
        self.logs_base_dir.mkdir(exist_ok=True)

        # Get current date in EST timezone
        self.current_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

        # Create daily folder (e.g., logs/2025-12-06/)
        self.log_dir = self.logs_base_dir / self.current_date
        self.log_dir.mkdir(exist_ok=True)

        # Create log files inside daily folder
        self.log_file: Path = self.log_dir / f"{_get_bot_name()}-{self.current_date}.log"
        self.error_file: Path = self.log_dir / f"{_get_bot_name()}-Errors-{self.current_date}.log"

        # Clean up old log folders (older than 7 days)
        self._cleanup_old_logs()

        # Write session header
        self._write_session_header()

    # =========================================================================
    # Private Methods - Setup
    # =========================================================================

    def _cleanup_old_logs(self) -> None:
        """Clean up log folders older than retention period (7 days)."""
        try:
            now = datetime.now(TIMEZONE)
            cutoff_date = now - timedelta(days=LOG_RETENTION_DAYS)
            deleted_count = 0

            # Use glob pattern to only match date-formatted folders (YYYY-MM-DD)
            for folder in self.logs_base_dir.glob("????-??-??"):
                if not folder.is_dir():
                    continue

                try:
                    folder_date = datetime.strptime(folder.name, "%Y-%m-%d")
                    folder_date = folder_date.replace(tzinfo=TIMEZONE)

                    if folder_date < cutoff_date:
                        shutil.rmtree(folder)
                        deleted_count += 1
                except ValueError:
                    continue

            if deleted_count > 0:
                print(f"[LOG CLEANUP] Deleted {deleted_count} old log folders (>{LOG_RETENTION_DAYS} days)")
        except Exception as e:
            print(f"[LOG CLEANUP ERROR] {type(e).__name__}: {e}")

    def _check_date_rotation(self) -> None:
        """Check if date has changed and rotate to new log folder if needed."""
        current_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

        if current_date != self.current_date:
            # Date has changed - rotate to new folder
            self.current_date = current_date
            self.log_dir = self.logs_base_dir / self.current_date
            self.log_dir.mkdir(exist_ok=True)
            self.log_file = self.log_dir / f"{_get_bot_name()}-{self.current_date}.log"
            self.error_file = self.log_dir / f"{_get_bot_name()}-Errors-{self.current_date}.log"

            # Write continuation header to new log files
            header = (
                f"\n{'='*60}\n"
                f"LOG ROTATION - Continuing session {self.run_id}\n"
                f"{self._get_timestamp()}\n"
                f"{'='*60}\n\n"
            )
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(header)
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(header)
            except (OSError, IOError):
                pass

    def _write_session_header(self) -> None:
        """Write session header to both log file and error log file."""
        header = (
            f"\n{'='*60}\n"
            f"NEW SESSION - RUN ID: {self.run_id}\n"
            f"{self._get_timestamp()}\n"
            f"{'='*60}\n\n"
        )
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(header)
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(header)
        except (OSError, IOError):
            pass

    # =========================================================================
    # Private Methods - Formatting
    # =========================================================================

    def _get_timestamp(self) -> str:
        """Get current timestamp in Eastern timezone (auto EST/EDT)."""
        try:
            current_time = datetime.now(TIMEZONE)
            tz_name = current_time.strftime("%Z")
            return f"[{current_time.strftime('%I:%M:%S %p')} {tz_name}]"
        except Exception:
            return datetime.now().strftime("[%I:%M:%S %p]")

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis from text to avoid duplicate emojis in output."""
        return EMOJI_PATTERN.sub("", text).strip()

    def _format_tree(self, items: List[Tuple[str, Any]]) -> str:
        """Format items as a tree."""
        if not items:
            return ""
        lines = []
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            lines.append(f"  {prefix} {key}: {value}")
        return "\n".join(lines)

    def _format_duration(self, seconds: float) -> str:
        """Format seconds into human-readable duration (e.g., '2d 5h 30m')."""
        if seconds < 0:
            return "0s"

        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 and not parts:  # Only show seconds if no larger units
            parts.append(f"{secs}s")

        return " ".join(parts) if parts else "0s"

    def _format_user(self, user: Any) -> Tuple[str, str]:
        """
        Extract user info for consistent logging.

        Returns:
            Tuple of (display_string, user_id_string)

        Handles discord.User, discord.Member, and Interaction objects.
        """
        try:
            # Handle Interaction objects
            if hasattr(user, "user"):
                user = user.user

            # Extract name and display name
            name = getattr(user, "name", "Unknown")
            display_name = getattr(user, "display_name", name)
            user_id = getattr(user, "id", "Unknown")

            # Format: "username (display_name)" or just "username" if same
            if name != display_name:
                display_str = f"{name} ({display_name})"
            else:
                display_str = name

            return (display_str, str(user_id))
        except Exception:
            return ("Unknown", "Unknown")

    def _get_uptime(self) -> str:
        """Get formatted uptime since logger initialization."""
        now = datetime.now(TIMEZONE)
        delta = now - self._start_time
        return self._format_duration(delta.total_seconds())

    # =========================================================================
    # Private Methods - File Writing
    # =========================================================================

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file."""
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _write_raw(self, message: str, also_to_error: bool = False) -> None:
        """Write raw message without timestamp (for tree branches)."""
        print(message)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{message}\n")
            if also_to_error:
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(f"{message}\n")
        except (OSError, IOError):
            pass

    def _write_to_file_only(self, message: str) -> None:
        """Write to log file only (no console, no webhook - avoids recursion)."""
        self._check_date_rotation()
        timestamp = self._get_timestamp()
        full_message = f"{timestamp} {message}"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    def _write_error(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write error message to both main log and error log file."""
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(f"{full_message}\n")
        except (OSError, IOError):
            pass

    # =========================================================================
    # Live Logs - Discord Webhook Streaming
    # =========================================================================

    def _send_live_log(self, formatted_tree: str) -> None:
        """Send a single tree log to Discord webhook immediately."""
        if not self._live_logs_enabled:
            return

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._async_send_live_log(formatted_tree))
            task.add_done_callback(self._handle_webhook_task_exception)
        except RuntimeError:
            # No event loop running yet
            pass

    def _handle_webhook_task_exception(self, task: asyncio.Task) -> None:
        """Handle exceptions from webhook tasks silently (already logged to file)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            # Already logged to file in _async_send_webhook, just consume the exception
            pass

    async def _async_send_live_log(self, formatted_tree: str) -> None:
        """Send a single tree log to Discord webhook."""
        payload = {
            "content": f"```\n{formatted_tree}\n```",
            "username": f"{_get_bot_name()} Logs",
        }
        try:
            await self._async_send_webhook(payload, self._live_logs_webhook_url)
        except Exception as e:
            # Log to file only to avoid recursion
            self._write_to_file_only(f"[LIVE LOG WEBHOOK] Failed: {type(e).__name__}: {e}")

    def _send_error_webhook(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌"
    ) -> None:
        """Send error to dedicated error webhook as tree format."""
        if not self._error_webhook_url:
            return

        # Format as tree (same as live logs)
        formatted = self._format_tree_for_live(title, items, emoji)
        payload = {
            "content": f"```\n{formatted}\n```",
            "username": f"{_get_bot_name()} Errors",
        }

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._async_send_webhook(payload, self._error_webhook_url))
            task.add_done_callback(self._handle_webhook_task_exception)
        except RuntimeError:
            pass

    async def _get_webhook_session(self) -> aiohttp.ClientSession:
        """Get or create persistent webhook session (thread-safe)."""
        # Lazy init lock to avoid event loop issues at import time
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()

        async with self._session_lock:
            if self._webhook_session is None or self._webhook_session.closed:
                self._webhook_session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                )
            return self._webhook_session

    async def _async_send_webhook(self, payload: dict, webhook_url: str) -> None:
        """Send webhook payload asynchronously using persistent session."""
        try:
            session = await self._get_webhook_session()
            async with session.post(webhook_url, json=payload) as response:
                if response.status >= 400:
                    # Log to file only (avoid recursion)
                    self._write_to_file_only(
                        f"[WEBHOOK] HTTP {response.status} sending to webhook"
                    )
        except asyncio.TimeoutError:
            self._write_to_file_only("[WEBHOOK] Timeout sending to webhook")
        except aiohttp.ClientError as e:
            self._write_to_file_only(f"[WEBHOOK] Client error: {type(e).__name__}")
        except Exception as e:
            self._write_to_file_only(f"[WEBHOOK] Error: {type(e).__name__}: {e}")

    async def close_webhook_session(self) -> None:
        """Close the persistent webhook session (call on shutdown)."""
        if self._webhook_session and not self._webhook_session.closed:
            await self._webhook_session.close()
            self._webhook_session = None

    def _format_tree_for_live(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "📦"
    ) -> str:
        """Format a tree log for the live buffer."""
        timestamp = self._get_timestamp()
        lines = [f"{timestamp} {emoji} {self._strip_emojis(title)}"]

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            lines.append(f"  {prefix} {key}: {value}")

        return "\n".join(lines)

    # =========================================================================
    # Private Methods - Tree Error Logging
    # =========================================================================

    def _tree_error(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌",
    ) -> None:
        """Log structured error data in tree format to both log files and live logs."""
        if not self._last_was_tree:
            self._write_raw("", also_to_error=True)

        self._write_error(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}", also_to_error=True)

        # Add empty line after error tree for readability
        self._write_raw("", also_to_error=True)
        self._last_was_tree = True

        # Send to live logs Discord webhook
        formatted = self._format_tree_for_live(title, items, emoji)
        self._send_live_log(formatted)

        # Also send to dedicated error webhook
        self._send_error_webhook(title, items, emoji)

    # =========================================================================
    # Public Methods - Log Levels
    # =========================================================================

    def info(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an informational message."""
        if details:
            self.tree(message, details, emoji="ℹ️")
        else:
            self._write(message, "ℹ️")
            self._last_was_tree = False

    def success(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a success message."""
        if details:
            self.tree(message, details, emoji="✅")
        else:
            self._write(message, "✅")
            self._last_was_tree = False

    def error(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an error message (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="❌")
        else:
            self._write_error(message, "❌")
            self._last_was_tree = False

    def warning(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a warning message (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="⚠️")
        else:
            self._write_error(message, "⚠️")
            self._last_was_tree = False

    def debug(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a debug message (only if DEBUG env var is set)."""
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            if details:
                self.tree(message, details, emoji="🔍")
            else:
                self._write(message, "🔍")
                self._last_was_tree = False

    def critical(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a critical/fatal error message (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="🚨")
        else:
            self._write_error(message, "🚨")
            self._last_was_tree = False

    def exception(self, message: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an exception with full traceback (also writes to error log and live logs)."""
        if details:
            self._tree_error(message, details, emoji="💥")
        else:
            self._write_error(message, "💥")
        try:
            tb = traceback.format_exc()
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
        except (OSError, IOError):
            pass

    # =========================================================================
    # Public Methods - Tree Formatting
    # =========================================================================

    def tree(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "📦"
    ) -> None:
        """
        Log structured data in tree format.

        Example output:

            [12:00:00 PM EST] 📦 Bot Ready
              ├─ Bot ID: 123456789
              ├─ Guilds: 5
              └─ Latency: 50ms

        Args:
            title: Tree title/header
            items: List of (key, value) tuples
            emoji: Emoji prefix for title
        """
        # Check if this is an error-level log based on emoji
        is_error = emoji in self.ERROR_EMOJIS

        if is_error:
            # Use error tree path (writes to error log + error webhook)
            self._tree_error(title, items, emoji)
            return

        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}")

        self._write_raw("")
        self._last_was_tree = True

        # Send to live logs Discord webhook
        formatted = self._format_tree_for_live(title, items, emoji)
        self._send_live_log(formatted)

    def tree_nested(
        self,
        title: str,
        data: Dict[str, Any],
        emoji: str = "📦",
        indent: int = 0
    ) -> None:
        """
        Log nested/hierarchical data in tree format.

        Example output:
            [12:00:00 PM EST] 📦 Channel State
              ├─ Voice
              │   ├─ Connected: True
              │   └─ Members: 5
              └─ Settings
                  ├─ Locked: False
                  └─ Limit: 10

        Args:
            title: Tree title/header
            data: Nested dictionary
            emoji: Emoji prefix for title
            indent: Current indentation level
        """
        if indent == 0:
            if not self._last_was_tree:
                self._write_raw("")
            self._write(title, emoji)

        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * (indent + 1)

            if isinstance(value, dict):
                self._write_raw(f"{indent_str}{prefix} {key}")
                self._render_nested(value, indent + 1, is_last)
            else:
                self._write_raw(f"{indent_str}{prefix} {key}: {value}")

        if indent == 0:
            self._write_raw("")
            self._last_was_tree = True

            # Send to live logs webhook
            formatted = self._format_nested_for_live(title, data, emoji)
            self._send_live_log(formatted)

    def _format_nested_for_live(
        self,
        title: str,
        data: Dict[str, Any],
        emoji: str = "📦"
    ) -> str:
        """Format nested tree data for webhook."""
        timestamp = self._get_timestamp()
        lines = [f"{timestamp} {emoji} {self._strip_emojis(title)}"]
        self._format_nested_lines(data, lines, indent=1)
        return "\n".join(lines)

    def _format_nested_lines(
        self,
        data: Dict[str, Any],
        lines: List[str],
        indent: int = 1
    ) -> None:
        """Recursively format nested data into lines."""
        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * indent

            if isinstance(value, dict):
                lines.append(f"{indent_str}{prefix} {key}")
                self._format_nested_lines(value, lines, indent + 1)
            else:
                lines.append(f"{indent_str}{prefix} {key}: {value}")

    def _render_nested(self, data: Dict[str, Any], indent: int, parent_is_last: bool) -> None:
        """Recursively render nested tree data."""
        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            indent_str = "  " * indent

            if isinstance(value, dict):
                self._write_raw(f"{indent_str}  {prefix} {key}")
                self._render_nested(value, indent + 1, is_last)
            else:
                self._write_raw(f"{indent_str}  {prefix} {key}: {value}")

    def tree_list(
        self,
        title: str,
        items: List[str],
        emoji: str = "📋"
    ) -> None:
        """
        Log a simple list in tree format.

        Example output:
            [12:00:00 PM EST] 📋 Trusted Users
              ├─ John#1234
              ├─ Jane#5678
              └─ Bob#9012

        Args:
            title: Tree title/header
            items: List of string items
            emoji: Emoji prefix for title
        """
        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {item}")

        self._write_raw("")
        self._last_was_tree = True

    def tree_section(
        self,
        title: str,
        sections: Dict[str, List[Tuple[str, Any]]],
        emoji: str = "📊"
    ) -> None:
        """
        Log multiple sections in tree format.

        Example output:
            [12:00:00 PM EST] 📊 Bot Stats
              ├─ TempVoice
              │   ├─ Active Channels: 5
              │   └─ Total Created: 100
              └─ XP System
                  ├─ Users: 500
                  └─ Total XP: 1.2M

        Args:
            title: Tree title/header
            sections: Dict of section_name -> [(key, value), ...]
            emoji: Emoji prefix for title
        """
        if not self._last_was_tree:
            self._write_raw("")

        self._write(title, emoji)

        section_names = list(sections.keys())
        for si, section_name in enumerate(section_names):
            section_is_last = si == len(section_names) - 1
            section_prefix = TreeSymbols.LAST if section_is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {section_prefix} {section_name}")

            items = sections[section_name]
            for ii, (key, value) in enumerate(items):
                item_is_last = ii == len(items) - 1
                item_prefix = TreeSymbols.LAST if item_is_last else TreeSymbols.BRANCH
                continuation = TreeSymbols.SPACE if section_is_last else TreeSymbols.PIPE
                self._write_raw(f"  {continuation} {item_prefix} {key}: {value}")

        self._write_raw("")
        self._last_was_tree = True

    def error_tree(
        self,
        title: str,
        error: Exception,
        context: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log an error with context in tree format.

        Example output:
            [12:00:00 PM EST] ❌ Channel Error
              ├─ Type: PermissionError
              ├─ Message: Cannot modify channel
              ├─ Channel: 123456789
              └─ User: John#1234

        Args:
            title: Error title/description
            error: The exception that occurred
            context: Additional context as (key, value) tuples
        """
        items: List[Tuple[str, Any]] = [
            ("Type", type(error).__name__),
            ("Message", str(error)),
        ]

        if context:
            items.extend(context)

        self._tree_error(title, items, emoji="❌")

    def startup_banner(
        self,
        bot_name: str,
        bot_id: int,
        guilds: int,
        latency: float,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log bot startup with a banner and tree format.

        Example output:
            ═══════════════════════════════════════
                    SyriaBot │ Run: a1b2c3d4
            ═══════════════════════════════════════

            [12:00:00 PM EST] 🤖 Bot Ready
              ├─ Bot ID: 123456789
              ├─ Guilds: 5
              └─ Latency: 50ms

        Args:
            bot_name: Name of the bot
            bot_id: Discord bot ID
            guilds: Number of guilds
            latency: WebSocket latency in ms
            extra: Additional startup info
        """
        # Build the banner
        banner_text = f"{bot_name} │ Run: {self.run_id}"
        banner_width = 43
        padding = (banner_width - len(banner_text)) // 2
        centered_text = " " * padding + banner_text

        banner = (
            f"{'═' * banner_width}\n"
            f"{centered_text}\n"
            f"{'═' * banner_width}"
        )

        # Print banner to console and file
        print(f"\n{banner}\n")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{banner}\n\n")
        except (OSError, IOError):
            pass

        # Send banner to webhook
        self._send_live_log(banner)

        # Now log the tree with details
        items: List[Tuple[str, Any]] = [
            ("Bot ID", bot_id),
            ("Guilds", guilds),
            ("Latency", f"{latency:.0f}ms"),
        ]

        if extra:
            items.extend(extra)

        self.tree("Bot Ready", items, emoji="🤖")

    def shutdown_tree(
        self,
        bot_name: str,
        reason: str = "Shutdown requested",
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log bot shutdown with banner and tree format.

        Example output:
            ═══════════════════════════════════════════
               SyriaBot │ Shutdown │ Run: a1b2c3d4
            ═══════════════════════════════════════════

            [12:00:00 PM EST] 👋 Bot Shutting Down
              ├─ Reason: Restart requested
              └─ Uptime: 3d 12h 5m

        Args:
            bot_name: Name of the bot
            reason: Reason for shutdown
            extra: Additional context as (key, value) tuples
        """
        # Build the shutdown banner
        banner_text = f"{bot_name} │ Shutdown │ Run: {self.run_id}"
        banner_width = max(43, len(banner_text) + 4)
        padding = (banner_width - len(banner_text)) // 2
        centered_text = " " * padding + banner_text

        banner = (
            f"{'═' * banner_width}\n"
            f"{centered_text}\n"
            f"{'═' * banner_width}"
        )

        # Print banner to console and file
        print(f"\n{banner}\n")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{banner}\n\n")
        except (OSError, IOError):
            pass

        # Send banner to webhook
        self._send_live_log(banner)

        # Now log the tree with details
        items: List[Tuple[str, Any]] = [
            ("Reason", reason),
            ("Uptime", self._get_uptime()),
        ]

        if extra:
            items.extend(extra)

        self.tree("Bot Shutting Down", items, emoji="👋")

    def cooldown(
        self,
        user: Any,
        command: str,
        remaining: float,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log a command cooldown event.

        Example output:
            [12:00:00 PM EST] ⏳ Command Cooldown
              ├─ User: john (Johnny)
              ├─ ID: 123456789
              ├─ Command: daily
              └─ Remaining: 2h 30m

        Args:
            user: Discord User, Member, or Interaction object
            command: Name of the command on cooldown
            remaining: Remaining cooldown in seconds
            extra: Additional context as (key, value) tuples
        """
        user_str, user_id = self._format_user(user)

        items: List[Tuple[str, Any]] = [
            ("User", user_str),
            ("ID", user_id),
            ("Command", command),
            ("Remaining", self._format_duration(remaining)),
        ]

        if extra:
            items.extend(extra)

        self.tree("Command Cooldown", items, emoji="⏳")

    def command_blocked(
        self,
        user: Any,
        reason: str,
        command: Optional[str] = None,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log a blocked command attempt.

        Example output:
            [12:00:00 PM EST] 🚫 Command Blocked
              ├─ User: john (Johnny)
              ├─ ID: 123456789
              ├─ Command: daily
              └─ Reason: DM not allowed

        Args:
            user: Discord User, Member, or Interaction object
            reason: Why the command was blocked
            command: Optional command name
            extra: Additional context as (key, value) tuples
        """
        user_str, user_id = self._format_user(user)

        items: List[Tuple[str, Any]] = [
            ("User", user_str),
            ("ID", user_id),
        ]

        if command:
            items.append(("Command", command))

        items.append(("Reason", reason))

        if extra:
            items.extend(extra)

        self.tree("Command Blocked", items, emoji="🚫")


# =============================================================================
# Module Export
# =============================================================================

# Create singleton instance
logger = Logger()

# Backwards compatibility alias
log = logger

__all__ = [
    "logger",
    "log",
    "Logger",
    "TreeSymbols",
    # Log emoji constants
    "LOG_EMOJI_SUCCESS",
    "LOG_EMOJI_ERROR",
    "LOG_EMOJI_WARNING",
    "LOG_EMOJI_INFO",
    "LOG_EMOJI_DEBUG",
    "LOG_EMOJI_CRITICAL",
    "LOG_EMOJI_EXCEPTION",
    "LOG_EMOJI_BAN",
    "LOG_EMOJI_MUTE",
    "LOG_EMOJI_WARN",
    "LOG_EMOJI_KICK",
    "LOG_EMOJI_LOCK",
    "LOG_EMOJI_UNLOCK",
    "LOG_EMOJI_TICKET",
    "LOG_EMOJI_APPEAL",
    "LOG_EMOJI_DATABASE",
    "LOG_EMOJI_API",
    "LOG_EMOJI_CACHE",
    "LOG_EMOJI_SECURITY",
    "LOG_EMOJI_USER",
    "LOG_EMOJI_STARTUP",
    "LOG_EMOJI_SHUTDOWN",
    "LOG_EMOJI_CASE",
    "LOG_EMOJI_DM",
    "LOG_EMOJI_VOICE",
    "LOG_EMOJI_BOOSTER",
    "LOG_EMOJI_COOLDOWN",
    "LOG_EMOJI_BLOCKED",
]
