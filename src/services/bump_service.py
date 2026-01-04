"""
TrippixnBot - Bump Reminder Service
===================================

Reminds staff to bump the server on Disboard every 2 hours.
Detects successful bumps from Disboard's "bump done" embed.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import discord
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.core import config, log
from src.utils.footer import set_footer_async


# =============================================================================
# Bump Reminder Service
# =============================================================================

class BumpService:
    """Service for reminding staff to bump the server on Disboard."""

    BUMP_INTERVAL = 2 * 60 * 60  # 2 hours in seconds
    DISBOARD_BOT_ID = 302050872383242240  # Disboard's bot ID
    DATA_FILE = Path(__file__).parent.parent.parent / "data" / "bump_data.json"

    def __init__(self):
        self.bot: discord.Client = None
        self.bump_channel_id: int = None
        self.ping_role_id: int = None
        self._task: asyncio.Task = None
        self._running = False
        self._last_bump_time: Optional[float] = None
        self._last_reminder_time: Optional[float] = None
        self._load_data()

    def setup(self, bot: discord.Client, channel_id: int, role_id: int) -> None:
        """Setup the bump service with bot, channel, and role to ping."""
        self.bot = bot
        self.bump_channel_id = channel_id
        self.ping_role_id = role_id
        log.tree("Bump Reminder Setup", [
            ("Channel ID", channel_id),
            ("Role ID", role_id),
            ("Interval", "2 hours"),
        ], emoji="📢")

    def start(self) -> None:
        """Start the bump reminder scheduler."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._reminder_loop())
        log.tree("Bump Scheduler Started", [
            ("Status", "Running"),
            ("Interval", "2 hours"),
        ], emoji="✅")

    def stop(self) -> None:
        """Stop the bump reminder scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("Bump scheduler stopped")

    def _load_data(self) -> None:
        """Load bump data from file."""
        try:
            if self.DATA_FILE.exists():
                with open(self.DATA_FILE, "r") as f:
                    data = json.load(f)
                    self._last_bump_time = data.get("last_bump_time")
                    self._last_reminder_time = data.get("last_reminder_time")

                if self._last_bump_time:
                    import time
                    elapsed_min = int((time.time() - self._last_bump_time) / 60)
                    log.tree("Bump Data Loaded", [
                        ("Last Bump", f"{elapsed_min} min ago"),
                    ], emoji="📊")
        except Exception as e:
            log.warning(f"Failed to load bump data: {e}")

    def _save_data(self) -> None:
        """Save bump data to file."""
        try:
            self.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.DATA_FILE, "w") as f:
                json.dump({
                    "last_bump_time": self._last_bump_time,
                    "last_reminder_time": self._last_reminder_time,
                }, f, indent=2)
        except Exception as e:
            log.warning(f"Failed to save bump data: {e}")

    def record_bump(self) -> None:
        """Record that a bump just happened."""
        import time
        self._last_bump_time = time.time()
        self._last_reminder_time = None  # Reset so we send a new reminder after cooldown
        self._save_data()

        log.tree("Bump Recorded", [
            ("Time", datetime.now(timezone.utc).strftime("%H:%M UTC")),
            ("Next Reminder", "in 2 hours"),
        ], emoji="✅")

    async def _reminder_loop(self) -> None:
        """Main loop that sends bump reminders."""
        import time

        # Wait for bot to fully initialize
        await asyncio.sleep(10)

        while self._running:
            try:
                # Check cooldown status
                if self._last_bump_time:
                    elapsed = time.time() - self._last_bump_time
                    remaining = self.BUMP_INTERVAL - elapsed

                    if remaining > 0:
                        # Still on cooldown, wait
                        remaining_min = int(remaining // 60)
                        log.tree("Bump Cooldown", [
                            ("Remaining", f"{remaining_min} min"),
                        ], emoji="⏳")
                        await asyncio.sleep(remaining + 5)
                        continue

                    # Cooldown expired - check if we already sent a reminder
                    if self._last_reminder_time and self._last_reminder_time > self._last_bump_time:
                        # Already sent a reminder, wait for next bump
                        log.tree("Bump Reminder", [
                            ("Status", "Already sent, waiting for bump"),
                        ], emoji="⏸️")
                        await asyncio.sleep(300)  # Check every 5 minutes
                        continue
                else:
                    # No recorded bump - just wait, don't spam
                    log.tree("Bump Service", [
                        ("Status", "No bump recorded, waiting"),
                    ], emoji="⏰")
                    await asyncio.sleep(self.BUMP_INTERVAL)
                    continue

                # Send reminder
                await self._send_reminder()
                self._last_reminder_time = time.time()
                self._save_data()

                log.tree("Bump Reminder", [
                    ("Status", "Sent, waiting for bump"),
                ], emoji="⏳")

                # Wait for next bump (check periodically)
                while self._running:
                    await asyncio.sleep(300)  # Check every 5 minutes
                    # If a new bump happened, break out to restart cooldown
                    if self._last_bump_time and self._last_bump_time > self._last_reminder_time:
                        break

            except Exception as e:
                log.error("Bump reminder failed", [
                    ("Error", type(e).__name__),
                    ("Message", str(e)),
                ])
                await asyncio.sleep(60)

    async def _send_reminder(self) -> None:
        """Send a bump reminder in the designated channel."""
        if not self.bot or not self.bump_channel_id:
            log.warning("Bump service not properly configured")
            return

        channel = self.bot.get_channel(self.bump_channel_id)
        if not channel:
            log.warning(f"Bump channel {self.bump_channel_id} not found")
            return

        try:
            role_mention = f"<@&{self.ping_role_id}>" if self.ping_role_id else ""

            embed = discord.Embed(
                title="Time to Bump!",
                description=(
                    "The server is ready to be bumped again!\n\n"
                    "**How to bump:**\n"
                    "Use </bump:947088344167366698> in this channel"
                ),
                color=0x24B7B7
            )
            embed.set_thumbnail(url="https://disboard.org/images/bot-command-image-bump.png")
            await set_footer_async(embed, self.bot)

            await channel.send(content=role_mention, embed=embed)

            log.tree("Bump Reminder Sent", [
                ("Channel", f"#{channel.name}"),
                ("Time", datetime.now(timezone.utc).strftime("%H:%M UTC")),
            ], emoji="📢")

        except discord.Forbidden:
            log.error("No permission to send bump reminder")
        except discord.HTTPException as e:
            log.error(f"Failed to send bump reminder: {e}")


# Global instance
bump_service = BumpService()
