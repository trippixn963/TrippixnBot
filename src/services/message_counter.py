"""
TrippixnBot - Message Counter Service
=====================================

Tracks all-time message count.
Persists to file to survive restarts.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import time
from datetime import datetime
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
    """Tracks all-time message count with persistence."""

    def __init__(self):
        self._count: int = 0
        self._lock = asyncio.Lock()
        self._save_task: asyncio.Task | None = None
        self._recent_timestamps: list[float] = []  # For activity tracking
        self._dirty: bool = False

    def _load_from_file(self) -> None:
        """Load count from persistent storage."""
        try:
            if DATA_FILE.exists():
                data = json.loads(DATA_FILE.read_text())
                self._count = data.get("count", 0)
                log.tree("Message Counter Loaded", [
                    ("Count", f"{self._count:,}"),
                ], emoji="📂")
        except Exception as e:
            log.warning(f"Could not load message counter: {e}")

    def _save_to_file(self) -> None:
        """Save count to persistent storage."""
        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "count": self._count,
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

    async def start(self) -> None:
        """Start the counter service."""
        self._load_from_file()
        self._save_task = asyncio.create_task(self._periodic_save())

        log.tree("Message Counter Started", [
            ("Total Count", f"{self._count:,}"),
        ], emoji="📊")

    async def stop(self) -> None:
        """Stop the counter service and save."""
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            self._save_to_file()
            log.info(f"Message counter saved: {self._count:,} messages")

    async def increment(self) -> None:
        """Increment the message count."""
        now = time.time()

        async with self._lock:
            self._count += 1
            self._dirty = True

            # Track for activity indicator
            self._recent_timestamps.append(now)
            cutoff = now - ACTIVITY_WINDOW
            self._recent_timestamps = [t for t in self._recent_timestamps if t > cutoff]

    def get_count(self) -> int:
        """Get the total message count."""
        return self._count

    def get_recent_count(self) -> int:
        """Get messages in the last minute (for activity indicator)."""
        now = time.time()
        cutoff = now - ACTIVITY_WINDOW
        return len([t for t in self._recent_timestamps if t > cutoff])

    def is_active(self) -> bool:
        """Check if chat is currently active (5+ messages in last minute)."""
        return self.get_recent_count() >= 5


# Global instance
message_counter = MessageCounter()
