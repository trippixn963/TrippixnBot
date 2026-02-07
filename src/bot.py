"""
TrippixnBot - Main Bot
======================

Personal Discord bot for portfolio stats dashboard.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

import os
import asyncio
import sys
import traceback
import discord
from discord.ext import commands

from src.core import config, log
from src.services import get_api_service
from src.handlers import on_ready, on_presence_update
from src.utils import http_session


# =============================================================================
# Global Exception Handler
# =============================================================================

def setup_exception_handlers() -> None:
    """Set up global exception handlers for unhandled errors."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        log.critical("Unhandled Exception", [
            ("Type", exc_type.__name__),
            ("Message", str(exc_value)),
        ])
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    def handle_unraisable(args):
        """Handle exceptions in __del__ methods and other unraisable contexts."""
        log.error("Unraisable Exception", [
            ("Object", str(args.object) if args.object else "None"),
            ("Type", type(args.exc_value).__name__ if args.exc_value else "Unknown"),
            ("Message", str(args.exc_value) if args.exc_value else "Unknown"),
        ])

    sys.excepthook = handle_exception
    sys.unraisablehook = handle_unraisable


def setup_asyncio_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    """Set up asyncio exception handler for unhandled task exceptions."""

    def handle_async_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exception = context.get("exception")
        message = context.get("message", "Unknown error")

        if exception:
            log.error("Asyncio Exception", [
                ("Message", message),
                ("Type", type(exception).__name__),
                ("Error", str(exception)),
            ])
        else:
            log.error("Asyncio Error", [
                ("Message", message),
            ])

    loop.set_exception_handler(handle_async_exception)


# =============================================================================
# Guild Protection
# =============================================================================

def _get_authorized_guilds() -> set:
    """Get authorized guild IDs from environment."""
    guilds = set()
    syria_id = os.getenv("GUILD_ID")
    mods_id = os.getenv("MODS_GUILD_ID")
    if syria_id:
        guilds.add(int(syria_id))
    if mods_id:
        guilds.add(int(mods_id))
    return guilds

AUTHORIZED_GUILD_IDS = _get_authorized_guilds()


# =============================================================================
# Bot Setup
# =============================================================================

class TrippixnBot(commands.Bot):
    """Personal bot for portfolio stats dashboard."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.presences = True
        intents.message_content = True

        super().__init__(
            command_prefix="!trp ",
            intents=intents,
            help_command=None,
            status=discord.Status.invisible,
        )

        self.api_service = get_api_service()
        self.api_service.set_bot(self)

    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        # Start shared HTTP session
        await http_session.start(user_agent="TrippixnBot/1.0")

        # Start FastAPI server
        await self.api_service.start()

    async def on_ready(self) -> None:
        """Handle ready event."""
        await on_ready(self)

        # Leave unauthorized guilds
        await self._leave_unauthorized_guilds()

    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        """Handle presence updates for developer status tracking."""
        await on_presence_update(self, before, after)

    # =========================================================================
    # Guild Protection
    # =========================================================================

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Leave immediately if guild is not authorized."""
        if not AUTHORIZED_GUILD_IDS:
            return
        if guild.id not in AUTHORIZED_GUILD_IDS:
            log.warning("Added To Unauthorized Guild - Leaving", [
                ("Guild", guild.name),
                ("ID", str(guild.id)),
            ])
            try:
                await guild.leave()
            except Exception as e:
                log.error("Failed To Leave Unauthorized Guild", [
                    ("Guild", guild.name),
                    ("Error", str(e)),
                ])

    async def _leave_unauthorized_guilds(self) -> None:
        """Leave any guilds not in AUTHORIZED_GUILD_IDS."""
        if not AUTHORIZED_GUILD_IDS:
            log.warning("Guild Protection Skipped", [
                ("Reason", "AUTHORIZED_GUILD_IDS is empty"),
            ])
            return

        unauthorized = [g for g in self.guilds if g.id not in AUTHORIZED_GUILD_IDS]
        if not unauthorized:
            return

        log.tree("Leaving Unauthorized Guilds", [
            ("Count", str(len(unauthorized))),
        ], emoji="⚠️")

        for guild in unauthorized:
            try:
                log.warning("Leaving Unauthorized Guild", [
                    ("Guild", guild.name),
                    ("ID", str(guild.id)),
                ])
                await guild.leave()
            except Exception as e:
                log.error("Failed To Leave Guild", [
                    ("Guild", guild.name),
                    ("Error", str(e)),
                ])

    async def close(self) -> None:
        """Clean shutdown."""
        log.tree("Shutting Down", [
            ("Bot", str(self.user)),
        ], emoji="🛑")
        await self.api_service.stop()
        await http_session.stop()
        await super().close()


# =============================================================================
# Entry Point
# =============================================================================

async def main() -> None:
    """Main entry point."""
    setup_exception_handlers()

    log.tree("Starting TrippixnBot", [
        ("Version", "1.0.0"),
        ("API Port", config.API_PORT),
        ("Guild ID", config.GUILD_ID),
    ], emoji="🚀")

    if not config.TOKEN:
        log.error("TRIPPIXN_BOT_TOKEN environment variable not set")
        return

    loop = asyncio.get_running_loop()
    setup_asyncio_exception_handler(loop)

    bot = TrippixnBot()

    try:
        await bot.start(config.TOKEN)
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    except discord.LoginFailure as e:
        log.critical("Login Failed", [
            ("Error", str(e)),
            ("Hint", "Check your bot token"),
        ])
    except discord.PrivilegedIntentsRequired as e:
        log.critical("Privileged Intents Required", [
            ("Error", str(e)),
            ("Hint", "Enable intents in Discord Developer Portal"),
        ])
    except Exception as e:
        log.critical("Fatal Error", [
            ("Type", type(e).__name__),
            ("Error", str(e)),
        ])
    finally:
        if not bot.is_closed():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
