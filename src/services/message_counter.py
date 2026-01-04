"""
TrippixnBot - Message Counter Service
=====================================

Tracks weekly message count, resets every Sunday 00:00 EST.
Persists to file to survive restarts.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.core import log


# =============================================================================
# Constants
# =============================================================================

EST = ZoneInfo("America/New_York")
DATA_FILE = Path("/root/TrippixnBot/data/message_counter.json")
SAVE_INTERVAL = 60  # Save every 60 seconds
ACTIVITY_WINDOW = 60  # Track messages in last 60 seconds for "active" indicator


# =============================================================================
# Message Counter
# =============================================================================

class MessageCounter:
    """Tracks weekly message count with Sunday reset and persistence."""

    def __init__(self):
        self._count: int = 0
        self._week_start: datetime = self._get_current_week_start()
        self._lock = asyncio.Lock()
        self._reset_task: asyncio.Task | None = None
        self._save_task: asyncio.Task | None = None
        self._recent_timestamps: list[float] = []  # For activity tracking
        self._dirty: bool = False  # Track if we need to save

    def _get_current_week_start(self) -> datetime:
        """Get the start of the current week (Sunday 00:00 EST)."""
        now = datetime.now(EST)
        # days_since_sunday: Sunday=0, Monday=1, ..., Saturday=6
        days_since_sunday = now.weekday() + 1  # weekday(): Monday=0, Sunday=6
        if days_since_sunday == 7:  # It's Sunday
            days_since_sunday = 0

        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start - timedelta(days=days_since_sunday)
        return week_start

    def _get_next_sunday_midnight(self) -> datetime:
        """Get the next Sunday 00:00 EST."""
        now = datetime.now(EST)
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 0:
            # It's Sunday but past midnight, so next Sunday
            days_until_sunday = 7

        next_sunday = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_sunday = next_sunday + timedelta(days=days_until_sunday)
        return next_sunday

    def _load_from_file(self) -> None:
        """Load count from persistent storage."""
        try:
            if DATA_FILE.exists():
                data = json.loads(DATA_FILE.read_text())
                saved_week_start = datetime.fromisoformat(data["week_start"])
                current_week_start = self._get_current_week_start()

                # Only restore if same week
                if saved_week_start.date() == current_week_start.date():
                    self._count = data["count"]
                    self._week_start = saved_week_start
                    log.tree("Message Counter Loaded", [
                        ("Count", f"{self._count:,}"),
                        ("Week Start", self._week_start.strftime("%Y-%m-%d")),
                    ], emoji="📂")
                else:
                    log.info("New week detected, starting fresh count")
        except Exception as e:
            log.warning(f"Could not load message counter: {e}")

    def _save_to_file(self) -> None:
        """Save count to persistent storage."""
        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "count": self._count,
                "week_start": self._week_start.isoformat(),
                "updated_at": datetime.now(EST).isoformat(),
            }
            DATA_FILE.write_text(json.dumps(data, indent=2))
            self._dirty = False
        except Exception as e:
            log.warning(f"Could not save message counter: {e}")

    async def _periodic_save(self) -> None:
        """Periodically save to file."""
        while True:
            await asyncio.sleep(SAVE_INTERVAL)
            if self._dirty:
                async with self._lock:
                    self._save_to_file()

    async def _schedule_reset(self) -> None:
        """Schedule the weekly reset."""
        while True:
            next_reset = self._get_next_sunday_midnight()
            now = datetime.now(EST)
            seconds_until_reset = (next_reset - now).total_seconds()

            if seconds_until_reset <= 0:
                # Already past reset time, schedule for next week
                next_reset = next_reset + timedelta(days=7)
                seconds_until_reset = (next_reset - now).total_seconds()

            log.tree("Message Counter Reset Scheduled", [
                ("Next Reset", next_reset.strftime("%Y-%m-%d %H:%M:%S EST")),
                ("In", f"{seconds_until_reset / 3600:.1f} hours"),
            ], emoji="⏰")

            await asyncio.sleep(seconds_until_reset)

            async with self._lock:
                old_count = self._count
                self._count = 0
                self._week_start = self._get_current_week_start()
                self._save_to_file()

                log.tree("Weekly Message Count Reset", [
                    ("Previous Count", f"{old_count:,}"),
                    ("New Week Start", self._week_start.strftime("%Y-%m-%d")),
                ], emoji="🔄")

    async def start(self) -> None:
        """Start the counter service."""
        # Load persisted data
        self._load_from_file()

        # Start background tasks
        self._reset_task = asyncio.create_task(self._schedule_reset())
        self._save_task = asyncio.create_task(self._periodic_save())

        log.tree("Message Counter Started", [
            ("Week Start", self._week_start.strftime("%Y-%m-%d")),
            ("Current Count", f"{self._count:,}"),
            ("Persistence", "Enabled"),
        ], emoji="📊")

    async def stop(self) -> None:
        """Stop the counter service and save."""
        # Cancel tasks
        for task in [self._reset_task, self._save_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Final save
        async with self._lock:
            self._save_to_file()
            log.info(f"Message counter saved: {self._count:,} messages")

    async def increment(self) -> None:
        """Increment the message count."""
        now = time.time()

        async with self._lock:
            # Check if we need to reset (in case scheduler missed)
            current_week_start = self._get_current_week_start()
            if current_week_start > self._week_start:
                self._count = 0
                self._week_start = current_week_start

            self._count += 1
            self._dirty = True

            # Track for activity indicator
            self._recent_timestamps.append(now)
            # Clean old timestamps
            cutoff = now - ACTIVITY_WINDOW
            self._recent_timestamps = [t for t in self._recent_timestamps if t > cutoff]

    def get_count(self) -> int:
        """Get the current weekly message count."""
        return self._count

    def get_recent_count(self) -> int:
        """Get messages in the last minute (for activity indicator)."""
        now = time.time()
        cutoff = now - ACTIVITY_WINDOW
        return len([t for t in self._recent_timestamps if t > cutoff])

    def is_active(self) -> bool:
        """Check if chat is currently active (5+ messages in last minute)."""
        return self.get_recent_count() >= 5

    def get_week_start(self) -> str:
        """Get the week start date as ISO string."""
        return self._week_start.isoformat()


# Global instance
message_counter = MessageCounter()
