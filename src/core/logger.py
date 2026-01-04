"""
TrippixnBot - Logger
====================

Custom logging system with tree-style formatting and EST timezone support.
Provides structured logging for Discord bot events with visual formatting
and file output for debugging and monitoring.

Features:
- Unique run ID generation for tracking bot sessions
- EST/EDT timezone timestamp formatting (auto-adjusts)
- Tree-style log formatting for structured data
- Nested tree support for hierarchical data
- Console and file output simultaneously
- Emoji-enhanced log levels for visual clarity
- Daily log folders with separate log and error files
- Automatic cleanup of old logs (7+ days)

Log Structure:
    logs/
    ├── 2025-12-15/
    │   ├── Trippixn-2025-12-15.log
    │   └── Trippixn-Errors-2025-12-15.log
    └── ...

Author: حَـــــنَّـــــا
"""

import atexit
import os
import re
import shutil
import threading
import uuid
import asyncio
import traceback
import aiohttp
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict, Generator
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

# Timezone: America/New_York (handles EST/EDT automatically)
_NY_TZ = ZoneInfo("America/New_York")

# Log retention period in days
LOG_RETENTION_DAYS = 7

# Max log file size before rotation (10MB)
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024

# Error webhook colors
COLOR_ERROR = 0xFF0000      # Red
COLOR_WARNING = 0xFFAA00    # Orange
COLOR_CRITICAL = 0x8B0000   # Dark Red

# Regex to match emojis
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

# Patterns that look like secrets - compiled for performance
SECRET_PATTERNS = [
    # Tokens and API keys
    (re.compile(r"(token[\"\']?\s*[:=]\s*[\"\']?)([a-zA-Z0-9_.-]{20,})", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(api[_-]?key[\"\']?\s*[:=]\s*[\"\']?)([a-zA-Z0-9_.-]{20,})", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(secret[\"\']?\s*[:=]\s*[\"\']?)([a-zA-Z0-9_.-]{20,})", re.IGNORECASE), r"\1***REDACTED***"),
    # Passwords
    (re.compile(r"(password[\"\']?\s*[:=]\s*[\"\']?)([^\s\"\']+)", re.IGNORECASE), r"\1***REDACTED***"),
    # Discord webhooks
    (re.compile(r"(webhook[s]?/\d+/)([a-zA-Z0-9_-]+)", re.IGNORECASE), r"\1***REDACTED***"),
    # Bearer tokens
    (re.compile(r"(Bearer\s+)([a-zA-Z0-9_.-]+)", re.IGNORECASE), r"\1***REDACTED***"),
    # Discord bot tokens (specific format)
    (re.compile(r"([A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,})"), r"***DISCORD_TOKEN_REDACTED***"),
]


# =============================================================================
# Tree Symbols
# =============================================================================

class TreeSymbols:
    """Box-drawing characters for tree formatting."""
    BRANCH = "├─"      # Middle item connector
    LAST = "└─"        # Last item connector
    PIPE = "│ "        # Vertical continuation
    SPACE = "  "       # Empty space for alignment
    HEADER = "┌─"      # Tree header
    FOOTER = "└─"      # Tree footer


# =============================================================================
# MiniTreeLogger
# =============================================================================

class MiniTreeLogger:
    """Custom logger with tree-style formatting and EST timezone support."""

    # =========================================================================
    # Initialization
    # =========================================================================

    def __init__(self) -> None:
        """Initialize the logger with unique run ID and daily log folder rotation."""
        self.run_id: str = str(uuid.uuid4())[:8]

        # Thread lock for file operations
        self._lock = threading.Lock()

        # Context stack for nested logging
        self._context_stack: List[str] = []

        # Base logs directory
        self.logs_base_dir = Path(__file__).parent.parent.parent / "logs"
        self.logs_base_dir.mkdir(exist_ok=True)

        # Timezone for date calculations
        self._timezone = _NY_TZ

        # Get current date in EST timezone
        self.current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")

        # Create daily folder (e.g., logs/2025-12-15/)
        self.log_dir = self.logs_base_dir / self.current_date
        self.log_dir.mkdir(exist_ok=True)

        # Create log files inside daily folder
        self.log_file: Path = self.log_dir / f"Trippixn-{self.current_date}.log"
        self.error_file: Path = self.log_dir / f"Trippixn-Errors-{self.current_date}.log"

        # Clean up old log folders (older than 7 days)
        self._cleanup_old_logs()

        # Write session header
        self._write_session_header()

        # Register shutdown handler
        atexit.register(self._shutdown)

    # =========================================================================
    # Private Methods - Setup
    # =========================================================================

    def _shutdown(self) -> None:
        """Clean shutdown - write final log entry."""
        try:
            with self._lock:
                shutdown_msg = (
                    f"\n{'='*60}\n"
                    f"SESSION END - RUN ID: {self.run_id}\n"
                    f"{self._get_timestamp()}\n"
                    f"{'='*60}\n\n"
                )
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(shutdown_msg)
        except Exception:
            pass

    def _check_log_size_rotation(self, file_path: Path) -> None:
        """Rotate log file if it exceeds max size."""
        try:
            if file_path.exists() and file_path.stat().st_size > MAX_LOG_SIZE_BYTES:
                # Find next rotation number
                rotation_num = 1
                while True:
                    rotated_path = file_path.with_suffix(f".{rotation_num}.log")
                    if not rotated_path.exists():
                        break
                    rotation_num += 1

                # Rename current file
                file_path.rename(rotated_path)

                # Write rotation notice to new file
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(
                        f"{'='*60}\n"
                        f"LOG ROTATED - Previous: {rotated_path.name}\n"
                        f"Session: {self.run_id} | {self._get_timestamp()}\n"
                        f"{'='*60}\n\n"
                    )
        except Exception:
            pass

    def _check_date_rotation(self) -> None:
        """Check if date has changed and rotate to new log folder if needed."""
        current_date = datetime.now(self._timezone).strftime("%Y-%m-%d")

        if current_date != self.current_date:
            # Date has changed - rotate to new folder
            self.current_date = current_date
            self.log_dir = self.logs_base_dir / self.current_date
            self.log_dir.mkdir(exist_ok=True)
            self.log_file = self.log_dir / f"Trippixn-{self.current_date}.log"
            self.error_file = self.log_dir / f"Trippixn-Errors-{self.current_date}.log"

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

    def _cleanup_old_logs(self) -> None:
        """Clean up log folders older than retention period (7 days)."""
        try:
            now = datetime.now(_NY_TZ)
            deleted_count = 0

            # Iterate through date folders in the logs directory
            for folder in self.logs_base_dir.iterdir():
                if not folder.is_dir():
                    continue

                # Skip non-date folders
                folder_name = folder.name
                try:
                    folder_date = datetime.strptime(folder_name, "%Y-%m-%d")
                    folder_date = folder_date.replace(tzinfo=_NY_TZ)
                except ValueError:
                    continue

                # Delete folders older than retention period
                days_old = (now - folder_date).days
                if days_old > LOG_RETENTION_DAYS:
                    shutil.rmtree(folder)
                    deleted_count += 1

            if deleted_count > 0:
                print(f"[LOG CLEANUP] Deleted {deleted_count} old log folders (>{LOG_RETENTION_DAYS} days)")
        except Exception as e:
            print(f"[LOG CLEANUP ERROR] {e}")

    def _write_session_header(self) -> None:
        """Write session header to both log file and error log file."""
        header = (
            f"\n{'='*60}\n"
            f"NEW SESSION - RUN ID: {self.run_id}\n"
            f"{self._get_timestamp()}\n"
            f"{'='*60}\n\n"
        )
        try:
            # Write to main log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(header)
            # Write to error log
            with open(self.error_file, "a", encoding="utf-8") as f:
                f.write(header)
        except (OSError, IOError):
            pass

    # =========================================================================
    # Private Methods - Error Webhook
    # =========================================================================

    def _send_error_webhook(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        color: int = COLOR_ERROR,
        emoji: str = "❌"
    ) -> None:
        """Send error to Discord webhook asynchronously."""
        # Read at runtime (after load_dotenv has been called)
        error_webhook_url = os.getenv("ERROR_WEBHOOK_URL", "")
        if not error_webhook_url:
            return

        try:
            # Build description from items
            description = "\n".join([f"**{key}:** `{value}`" for key, value in items])

            embed = {
                "title": f"{emoji} {title}",
                "description": description,
                "color": color,
                "timestamp": datetime.now(_NY_TZ).isoformat(),
                "footer": {"text": f"Run ID: {self.run_id}"}
            }

            payload = {"embeds": [embed]}

            # Try to send asynchronously if event loop is running
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._async_send_webhook(payload, error_webhook_url))
            except RuntimeError:
                # No event loop running, skip webhook
                pass
        except Exception as e:
            # Log webhook errors to stderr to avoid breaking main logging
            import sys
            print(f"[LOGGER] Webhook setup error: {e}", file=sys.stderr)

    async def _async_send_webhook(self, payload: dict, webhook_url: str) -> None:
        """Send webhook payload asynchronously."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    pass  # Fire and forget
        except Exception as e:
            # Log webhook errors to stderr to avoid recursion
            import sys
            print(f"[LOGGER] Webhook send error: {e}", file=sys.stderr)

    # =========================================================================
    # Private Methods - Formatting
    # =========================================================================

    def _get_timestamp(self) -> str:
        """Get current timestamp in Eastern timezone (auto EST/EDT)."""
        try:
            current_time = datetime.now(_NY_TZ)
            tz_name = current_time.strftime("%Z")
            return current_time.strftime(f"[%I:%M:%S %p {tz_name}]")
        except Exception:
            return datetime.now().strftime("[%I:%M:%S %p]")

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis from text to avoid duplicate emojis in output."""
        return EMOJI_PATTERN.sub("", text).strip()

    def _mask_secrets(self, text: str) -> str:
        """
        Mask potential secrets in text before logging.

        This prevents accidental exposure of sensitive data like tokens,
        API keys, passwords, and webhooks in log files.
        """
        if not text:
            return text

        result = text
        for pattern, replacement in SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def _write(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write log message to both console and file (thread-safe)."""
        # Check if we need to rotate to a new date folder
        self._check_date_rotation()

        # Strip any emojis from the message to avoid duplicates
        clean_message = self._strip_emojis(message)

        # Mask any potential secrets in the message
        clean_message = self._mask_secrets(clean_message)

        # Add context prefix if in a context block
        if self._context_stack:
            context_prefix = " > ".join(self._context_stack)
            clean_message = f"[{context_prefix}] {clean_message}"

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        with self._lock:
            try:
                self._check_log_size_rotation(self.log_file)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"{full_message}\n")
            except (OSError, IOError):
                pass

    def _write_raw(self, message: str, also_to_error: bool = False) -> None:
        """Write raw message without timestamp (for tree branches, thread-safe)."""
        # Mask any potential secrets in the message
        safe_message = self._mask_secrets(message)

        print(safe_message)
        with self._lock:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"{safe_message}\n")
                if also_to_error:
                    with open(self.error_file, "a", encoding="utf-8") as f:
                        f.write(f"{safe_message}\n")
            except (OSError, IOError):
                pass

    def _write_error(self, message: str, emoji: str = "", include_timestamp: bool = True) -> None:
        """Write error message to both main log and error log file (thread-safe)."""
        # Check if we need to rotate to a new date folder
        self._check_date_rotation()

        clean_message = self._strip_emojis(message)

        # Mask any potential secrets in the message
        clean_message = self._mask_secrets(clean_message)

        # Add context prefix if in a context block
        if self._context_stack:
            context_prefix = " > ".join(self._context_stack)
            clean_message = f"[{context_prefix}] {clean_message}"

        if include_timestamp:
            timestamp = self._get_timestamp()
            full_message = f"{timestamp} {emoji} {clean_message}" if emoji else f"{timestamp} {clean_message}"
        else:
            full_message = f"{emoji} {clean_message}" if emoji else clean_message

        print(full_message)

        with self._lock:
            try:
                self._check_log_size_rotation(self.log_file)
                self._check_log_size_rotation(self.error_file)
                # Write to main log
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"{full_message}\n")
                # Write to error log
                with open(self.error_file, "a", encoding="utf-8") as f:
                    f.write(f"{full_message}\n")
            except (OSError, IOError):
                pass

    def _tree_error(
        self,
        title: str,
        items: List[Tuple[str, Any]],
        emoji: str = "❌",
        color: int = COLOR_ERROR
    ) -> None:
        """Log structured error data in tree format to both log files and webhook."""
        self._write_error(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}", also_to_error=True)

        self._write_raw("", also_to_error=True)  # Empty line after tree

        # Send to Discord webhook
        self._send_error_webhook(title, items, color, emoji)

    # =========================================================================
    # Public Methods - Log Levels (All output as tree format)
    # =========================================================================

    def info(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an informational message as a tree."""
        if details:
            self.tree(msg, details, emoji="ℹ️")
        else:
            self._write(msg, "ℹ️")
            self._write_raw(f"  {TreeSymbols.LAST} Status: OK")
            self._write_raw("")  # Empty line after tree

    def success(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a success message as a tree."""
        if details:
            self.tree(msg, details, emoji="✅")
        else:
            self._write(msg, "✅")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Complete")
            self._write_raw("")  # Empty line after tree

    def error(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an error message as a tree (also writes to error log and webhook)."""
        if details:
            self._tree_error(msg, details, emoji="❌", color=COLOR_ERROR)
        else:
            self._write_error(msg, "❌")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Failed", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree
            # Also send simple errors to webhook
            self._send_error_webhook(msg, [("Level", "Error")], COLOR_ERROR, "❌")

    def warning(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a warning message as a tree (also writes to error log and webhook)."""
        if details:
            self._tree_error(msg, details, emoji="⚠️", color=COLOR_WARNING)
        else:
            self._write_error(msg, "⚠️")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Warning", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree
            # Also send simple warnings to webhook
            self._send_error_webhook(msg, [("Level", "Warning")], COLOR_WARNING, "⚠️")

    def debug(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a debug message (only if DEBUG env var is set)."""
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            if details:
                self.tree(msg, details, emoji="🔍")
            else:
                self._write(msg, "🔍")
                self._write_raw(f"  {TreeSymbols.LAST} Status: Debug")
                self._write_raw("")  # Empty line after tree

    def critical(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log a critical/fatal error message as a tree (also writes to error log and webhook)."""
        if details:
            self._tree_error(msg, details, emoji="🚨", color=COLOR_CRITICAL)
        else:
            self._write_error(msg, "🚨")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Critical", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree
            # Also send simple critical errors to webhook
            self._send_error_webhook(msg, [("Level", "Critical")], COLOR_CRITICAL, "🚨")

    def exception(self, msg: str, details: Optional[List[Tuple[str, Any]]] = None) -> None:
        """Log an exception with full traceback as a tree (also writes to error log and webhook)."""
        if details:
            self._tree_error(msg, details, emoji="💥", color=COLOR_CRITICAL)
        else:
            self._write_error(msg, "💥")
            self._write_raw(f"  {TreeSymbols.LAST} Status: Exception", also_to_error=True)
            self._write_raw("", also_to_error=True)  # Empty line after tree
            # Also send simple exception errors to webhook
            self._send_error_webhook(msg, [("Level", "Exception")], COLOR_CRITICAL, "💥")
        try:
            tb = traceback.format_exc()
            # Write traceback to main log
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(tb)
                f.write("\n")
            # Write traceback to error log
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
        self._write(title, emoji)

        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {key}: {value}")

        self._write_raw("")  # Empty line after tree

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
            [12:00:00 PM EST] 📦 Stats Update
              ├─ Guild
              │   ├─ Members: 100
              │   └─ Online: 50
              └─ Developer
                  ├─ Status: online
                  └─ Activities: 2

        Args:
            title: Tree title/header
            data: Nested dictionary
            emoji: Emoji prefix for title
            indent: Current indentation level
        """
        if indent == 0:
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
            self._write_raw("")  # Empty line after tree

    def _render_nested(self, data: Dict[str, Any], indent: int, parent_is_last: bool) -> None:
        """Recursively render nested tree data."""
        items = list(data.items())
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH

            # Build proper indentation with pipes
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
            [12:00:00 PM EST] 📋 Active Services
              ├─ Stats API
              ├─ Presence Handler
              └─ Stats Collector

        Args:
            title: Tree title/header
            items: List of string items
            emoji: Emoji prefix for title
        """
        self._write(title, emoji)

        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            prefix = TreeSymbols.LAST if is_last else TreeSymbols.BRANCH
            self._write_raw(f"  {prefix} {item}")

        self._write_raw("")  # Empty line after tree

    def tree_section(
        self,
        title: str,
        sections: Dict[str, List[Tuple[str, Any]]],
        emoji: str = "📊"
    ) -> None:
        """
        Log multiple sections in tree format.

        Example output:
            [12:00:00 PM EST] 📊 Server Stats
              ├─ Guild
              │   ├─ Name: My Server
              │   └─ Members: 100
              └─ Bots
                  ├─ Taha: Online
                  └─ Othman: Online

        Args:
            title: Tree title/header
            sections: Dict of section_name -> [(key, value), ...]
            emoji: Emoji prefix for title
        """
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

                # Use pipe continuation for non-last sections
                continuation = TreeSymbols.SPACE if section_is_last else TreeSymbols.PIPE
                self._write_raw(f"  {continuation} {item_prefix} {key}: {value}")

        self._write_raw("")  # Empty line after tree

    def error_tree(
        self,
        title: str,
        error: Exception,
        context: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log an error with context in tree format.

        Example output:
            [12:00:00 PM EST] ❌ API Error
              ├─ Type: ConnectionError
              ├─ Message: Failed to connect
              ├─ Endpoint: /api/stats
              └─ Action: update_stats

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

        self.tree(title, items, emoji="❌")

    def startup_tree(
        self,
        bot_name: str,
        bot_id: int,
        guilds: int,
        latency: float,
        extra: Optional[List[Tuple[str, Any]]] = None
    ) -> None:
        """
        Log bot startup information in tree format.

        Args:
            bot_name: Name of the bot
            bot_id: Discord bot ID
            guilds: Number of guilds
            latency: WebSocket latency in ms
            extra: Additional startup info
        """
        items: List[Tuple[str, Any]] = [
            ("Bot ID", bot_id),
            ("Guilds", guilds),
            ("Latency", f"{latency:.0f}ms"),
            ("Run ID", self.run_id),
        ]

        if extra:
            items.extend(extra)

        self.tree(f"Bot Ready: {bot_name}", items, emoji="🤖")

    # =========================================================================
    # Public Methods - Context Manager
    # =========================================================================

    @contextmanager
    def context(self, name: str) -> Generator[None, None, None]:
        """
        Context manager for grouping related log entries.

        All log messages within this context will be prefixed with the context name,
        making it easier to trace related operations in the logs.

        Example:
            with log.context("Download"):
                log.info("Starting download")
                log.info("Download complete")

        Output:
            [12:00:00 PM EST] ℹ️ [Download] Starting download
            [12:00:00 PM EST] ℹ️ [Download] Download complete

        Contexts can be nested:
            with log.context("User:123"):
                with log.context("Download"):
                    log.info("Fetching")  # [User:123 > Download] Fetching

        Args:
            name: Context name to prefix log messages with
        """
        self._context_stack.append(name)
        try:
            yield
        finally:
            self._context_stack.pop()

    def get_log_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current logging session.

        Returns:
            Dictionary with log file sizes, paths, and session info
        """
        stats: Dict[str, Any] = {
            "run_id": self.run_id,
            "current_date": self.current_date,
            "log_dir": str(self.log_dir),
        }

        try:
            if self.log_file.exists():
                stats["log_file_size"] = self.log_file.stat().st_size
                stats["log_file_size_mb"] = round(stats["log_file_size"] / (1024 * 1024), 2)
            if self.error_file.exists():
                stats["error_file_size"] = self.error_file.stat().st_size
                stats["error_file_size_mb"] = round(stats["error_file_size"] / (1024 * 1024), 2)
        except Exception:
            pass

        return stats


# =============================================================================
# Module Export
# =============================================================================

log = MiniTreeLogger()

__all__ = ["log", "MiniTreeLogger", "TreeSymbols"]
