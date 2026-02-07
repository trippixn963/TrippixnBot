"""
TrippixnBot - Stats Store
=========================

Thread-safe stats storage with GitHub commit tracking.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core import log
from src.api.services.github import fetch_github_commits
from src.api.services.websocket import get_ws_manager


class StatsStore:
    """Thread-safe stats storage."""

    def __init__(self):
        self._stats: dict = {
            "guild": {
                "name": "",
                "id": 0,
                "icon": None,
                "banner": None,
                "member_count": 0,
                "online_count": 0,
                "boost_level": 0,
                "boost_count": 0,
                "total_messages": 0,
                "chat_active": False,
                "created_at": None,
                "moderators": [],
            },
            "bots": {
                "taha": {"online": False},
                "othman": {"online": False},
            },
            "developer": {
                "status": "offline",
                "avatar": None,
                "banner": None,
                "decoration": None,
                "activities": [],
            },
            "commits": {
                "this_year": 0,
                "year_start": None,
                "last_fetched": None,
                "calendar": [],
            },
            "updated_at": None,
        }
        self._lock = asyncio.Lock()
        self._commits_file = Path(os.getenv("DATA_DIR", "/root/TrippixnBot/data")) / "commits.json"
        self._github_task: Optional[asyncio.Task] = None
        self._load_commits()

    def _load_commits(self) -> None:
        """Load cached commits from file."""
        try:
            if self._commits_file.exists():
                with open(self._commits_file, "r") as f:
                    self._stats["commits"] = json.load(f)
        except Exception as e:
            log.warning("Load Commits Cache Failed", [("Error", str(e))])

    def _save_commits(self) -> None:
        """Save commits to cache file."""
        try:
            self._commits_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._commits_file, "w") as f:
                json.dump(self._stats["commits"], f)
        except Exception as e:
            log.warning("Save Commits Cache Failed", [("Error", str(e))])

    async def refresh_github_commits(self) -> int:
        """Fetch and update GitHub commits."""
        result = await fetch_github_commits()

        if result:
            async with self._lock:
                self._stats["commits"]["this_year"] = result["total"]
                self._stats["commits"]["year_start"] = result["year_start"]
                self._stats["commits"]["last_fetched"] = result["fetched_at"]
                self._stats["commits"]["calendar"] = result["calendar"]
                self._save_commits()

            log.debug("GitHub Commits Updated", [
                ("Total", str(result["total"])),
            ])
            return result["total"]

        return self._stats["commits"].get("this_year", 0)

    async def start_github_polling(self) -> None:
        """Start background task to poll GitHub commits hourly."""
        async def poll_loop():
            while True:
                await self.refresh_github_commits()
                await asyncio.sleep(3600)  # Every hour

        # Fetch immediately
        await self.refresh_github_commits()
        # Start polling
        self._github_task = asyncio.create_task(poll_loop())

    async def stop_github_polling(self) -> None:
        """Stop the GitHub polling task."""
        if self._github_task:
            self._github_task.cancel()
            try:
                await self._github_task
            except asyncio.CancelledError:
                pass

    async def update(self, **kwargs) -> None:
        """Update stats and broadcast to WebSocket clients."""
        async with self._lock:
            for key, value in kwargs.items():
                if key in self._stats:
                    if isinstance(value, dict) and isinstance(self._stats[key], dict):
                        self._stats[key].update(value)
                    else:
                        self._stats[key] = value

        # Broadcast update to WebSocket clients
        ws_manager = get_ws_manager()
        if ws_manager.connection_count > 0:
            await ws_manager.broadcast({
                "type": "stats",
                "data": self._stats.copy(),
            })

    async def get(self) -> dict:
        """Get current stats."""
        async with self._lock:
            return self._stats.copy()

    def get_sync(self) -> dict:
        """Get current stats (synchronous)."""
        return self._stats.copy()


# Singleton
_stats_store: Optional[StatsStore] = None


def get_stats_store() -> StatsStore:
    """Get stats store singleton."""
    global _stats_store
    if _stats_store is None:
        _stats_store = StatsStore()
    return _stats_store


__all__ = ["StatsStore", "get_stats_store"]
