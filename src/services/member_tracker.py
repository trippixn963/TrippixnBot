"""
TrippixnBot - Member Growth Tracker
===================================

Tracks weekly member growth, resets every Sunday 00:00 EST.
Persists to file to survive restarts.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.core import log


# =============================================================================
# Constants
# =============================================================================

EST = ZoneInfo("America/New_York")
DATA_FILE = Path("/root/TrippixnBot/data/member_tracker.json")
SAVE_INTERVAL = 300  # Save every 5 minutes


# =============================================================================
# Member Growth Tracker
# =============================================================================

class MemberTracker:
    """Tracks weekly member growth with Sunday reset and persistence."""

    def __init__(self):
        self._week_start_count: int = 0  # Member count at start of week
        self._current_count: int = 0
        self._week_start: datetime = self._get_current_week_start()
        self._lock = asyncio.Lock()
        self._reset_task: asyncio.Task | None = None
        self._save_task: asyncio.Task | None = None
        self._dirty: bool = False

    def _get_current_week_start(self) -> datetime:
        """Get the start of the current week (Sunday 00:00 EST)."""
        now = datetime.now(EST)
        days_since_sunday = now.weekday() + 1
        if days_since_sunday == 7:
            days_since_sunday = 0

        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start - timedelta(days=days_since_sunday)
        return week_start

    def _get_next_sunday_midnight(self) -> datetime:
        """Get the next Sunday 00:00 EST."""
        now = datetime.now(EST)
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 0:
            days_until_sunday = 7

        next_sunday = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_sunday = next_sunday + timedelta(days=days_until_sunday)
        return next_sunday

    def _load_from_file(self) -> None:
        """Load data from persistent storage."""
        try:
            if DATA_FILE.exists():
                data = json.loads(DATA_FILE.read_text())
                saved_week_start = datetime.fromisoformat(data["week_start"])
                current_week_start = self._get_current_week_start()

                if saved_week_start.date() == current_week_start.date():
                    self._week_start_count = data["week_start_count"]
                    self._current_count = data.get("current_count", self._week_start_count)
                    self._week_start = saved_week_start
                    log.tree("Member Tracker Loaded", [
                        ("Week Start Count", f"{self._week_start_count:,}"),
                        ("Current Count", f"{self._current_count:,}"),
                        ("Growth", f"+{self.get_growth():,}"),
                    ], emoji="📂")
                else:
                    log.info("New week detected for member tracker")
        except Exception as e:
            log.warning(f"Could not load member tracker: {e}")

    def _save_to_file(self) -> None:
        """Save data to persistent storage."""
        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "week_start_count": self._week_start_count,
                "current_count": self._current_count,
                "week_start": self._week_start.isoformat(),
                "updated_at": datetime.now(EST).isoformat(),
            }
            DATA_FILE.write_text(json.dumps(data, indent=2))
            self._dirty = False
        except Exception as e:
            log.warning(f"Could not save member tracker: {e}")

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
                next_reset = next_reset + timedelta(days=7)
                seconds_until_reset = (next_reset - now).total_seconds()

            log.tree("Member Tracker Reset Scheduled", [
                ("Next Reset", next_reset.strftime("%Y-%m-%d %H:%M:%S EST")),
                ("In", f"{seconds_until_reset / 3600:.1f} hours"),
            ], emoji="⏰")

            await asyncio.sleep(seconds_until_reset)

            async with self._lock:
                old_growth = self.get_growth()
                # Reset: new week starts with current count as baseline
                self._week_start_count = self._current_count
                self._week_start = self._get_current_week_start()
                self._save_to_file()

                log.tree("Weekly Member Growth Reset", [
                    ("Previous Growth", f"+{old_growth:,}"),
                    ("New Baseline", f"{self._week_start_count:,}"),
                ], emoji="🔄")

    async def start(self, initial_count: int) -> None:
        """Start the tracker service with initial member count."""
        self._current_count = initial_count
        self._load_from_file()

        # If no saved data or new week, use current count as baseline
        if self._week_start_count == 0:
            self._week_start_count = initial_count
            self._dirty = True

        # Start background tasks
        self._reset_task = asyncio.create_task(self._schedule_reset())
        self._save_task = asyncio.create_task(self._periodic_save())

        log.tree("Member Tracker Started", [
            ("Week Start", self._week_start.strftime("%Y-%m-%d")),
            ("Baseline", f"{self._week_start_count:,}"),
            ("Current", f"{self._current_count:,}"),
            ("Growth", f"+{self.get_growth():,}"),
        ], emoji="📈")

    async def stop(self) -> None:
        """Stop the tracker service and save."""
        for task in [self._reset_task, self._save_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        async with self._lock:
            self._save_to_file()
            log.info(f"Member tracker saved: +{self.get_growth():,} this week")

    def update_count(self, count: int) -> None:
        """Update the current member count."""
        self._current_count = count
        self._dirty = True

    def get_growth(self) -> int:
        """Get members gained this week."""
        return max(0, self._current_count - self._week_start_count)

    def get_week_start(self) -> str:
        """Get the week start date as ISO string."""
        return self._week_start.isoformat()


# Global instance
member_tracker = MemberTracker()
