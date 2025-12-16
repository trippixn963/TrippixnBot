"""
TrippixnBot - Main Bot
======================

Personal Discord bot for portfolio stats and utilities.

Author: حَـــــنَّـــــا
"""

import asyncio
import discord
from discord.ext import commands

from src.core import config, log
from src.services import StatsAPI
from src.handlers import on_ready, on_presence_update, on_message, on_automod_action


# =============================================================================
# Bot Setup
# =============================================================================

class TrippixnBot(commands.Bot):
    """Personal bot for portfolio and utilities."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.presences = True
        intents.message_content = True  # Required for reading message content

        super().__init__(
            command_prefix="!trp ",
            intents=intents,
            help_command=None,
        )

        self.stats_api = StatsAPI()

    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        # Start stats API server
        await self.stats_api.start()

        # Load command cogs
        await self.load_extension("src.commands.download")
        await self.load_extension("src.commands.translate")
        await self.load_extension("src.commands.image")

        # Sync slash commands to the guild
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.success(f"Slash commands synced to guild {config.GUILD_ID}")

    async def on_ready(self) -> None:
        """Handle ready event."""
        await on_ready(self)

    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        """Handle presence updates."""
        await on_presence_update(before, after)

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        await on_message(self, message)
        await self.process_commands(message)

    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        """Handle AutoMod actions - respond when developer ping is blocked."""
        await on_automod_action(self, execution)

    async def close(self) -> None:
        """Clean shutdown."""
        log.tree("Shutting Down", [
            ("Bot", str(self.user)),
            ("Reason", "Clean shutdown"),
        ], emoji="🛑")
        await self.stats_api.stop()
        await super().close()


# =============================================================================
# Entry Point
# =============================================================================

async def main() -> None:
    """Main entry point."""
    log.tree("Starting TrippixnBot", [
        ("Version", "1.0.0"),
        ("API Port", config.API_PORT),
        ("Guild ID", config.GUILD_ID),
    ], emoji="🚀")

    if not config.TOKEN:
        log.error("TRIPPIXN_BOT_TOKEN environment variable not set")
        return

    bot = TrippixnBot()

    try:
        await bot.start(config.TOKEN)
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
