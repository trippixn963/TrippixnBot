"""
TrippixnBot - Main Bot
======================

Personal Discord bot for portfolio stats and utilities.

Author: حَـــــنَّـــــا
"""

import asyncio
import sys
import traceback
import discord
from discord.ext import commands

from src.core import config, log
from src.services import StatsAPI, server_intel, rag_service, auto_learner, style_learner, feedback_learner
from src.services.bump_service import bump_service
from src.handlers import on_ready, on_presence_update, on_message, on_automod_action
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
        # Also print traceback for debugging
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
# Bot Setup
# =============================================================================

class TrippixnBot(commands.Bot):
    """Personal bot for portfolio and utilities."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.presences = True
        intents.message_content = True  # Required for reading message content
        intents.auto_moderation_execution = True  # Required for automod ping interception

        super().__init__(
            command_prefix="!trp ",
            intents=intents,
            help_command=None,
            status=discord.Status.invisible,
        )

        self.stats_api = StatsAPI()

        # Set up app command error handler
        self.tree.on_error = self._on_app_command_error

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """Handle app command errors globally."""
        # Unwrap the original exception if it's wrapped
        original = getattr(error, "original", error)

        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await self._send_error_response(
                interaction,
                f"Command on cooldown. Try again in {error.retry_after:.1f}s"
            )
        elif isinstance(error, discord.app_commands.MissingPermissions):
            await self._send_error_response(
                interaction,
                "You don't have permission to use this command."
            )
        elif isinstance(error, discord.app_commands.CheckFailure):
            await self._send_error_response(
                interaction,
                "You cannot use this command."
            )
        elif isinstance(original, discord.HTTPException):
            log.error("Discord HTTP Error", [
                ("Command", interaction.command.name if interaction.command else "Unknown"),
                ("Status", original.status),
                ("Code", original.code),
                ("Message", original.text),
            ])
            await self._send_error_response(
                interaction,
                "Discord API error. Please try again later."
            )
        elif isinstance(original, asyncio.TimeoutError):
            log.warning("Command Timeout", [
                ("Command", interaction.command.name if interaction.command else "Unknown"),
                ("User", str(interaction.user)),
            ])
            await self._send_error_response(
                interaction,
                "The operation timed out. Please try again."
            )
        else:
            log.error("App Command Error", [
                ("Command", interaction.command.name if interaction.command else "Unknown"),
                ("User", str(interaction.user)),
                ("Type", type(original).__name__),
                ("Error", str(original)),
            ])
            await self._send_error_response(
                interaction,
                "An error occurred while running this command."
            )

    async def _send_error_response(
        self,
        interaction: discord.Interaction,
        message: str
    ) -> None:
        """Safely send an error response to an interaction."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass  # Cannot respond, interaction may have expired

    async def on_error(self, event_method: str, *args, **kwargs) -> None:
        """Handle errors in event handlers."""
        exc_info = sys.exc_info()
        if exc_info[0] is None:
            return

        log.error(f"Event Handler Error: {event_method}", [
            ("Type", exc_info[0].__name__ if exc_info[0] else "Unknown"),
            ("Message", str(exc_info[1]) if exc_info[1] else "Unknown"),
        ])

    async def setup_hook(self) -> None:
        """Called when the bot is starting up."""
        # Start shared HTTP session
        await http_session.start()

        # Start stats API server
        await self.stats_api.start()

        # =================================================================
        # COMMANDS DISABLED - Will be moved to another bot
        # =================================================================
        # await self.load_extension("src.commands.download")
        # await self.load_extension("src.commands.translate")
        # await self.load_extension("src.commands.image")
        # await self.load_extension("src.commands.convert")

        # =================================================================
        # OWNER-ONLY COMMANDS
        # =================================================================
        await self.load_extension("src.commands.write")

        # Sync commands globally (works in DMs and all servers)
        await self.tree.sync()
        log.info("Commands synced globally")

    async def on_ready(self) -> None:
        """Handle ready event."""
        await on_ready(self)

        # Initialize server intelligence (only once, not on reconnects)
        if config.GUILD_ID and not server_intel._initialized:
            await server_intel.setup(self, config.GUILD_ID)

        # Initialize RAG service (only once)
        if not rag_service._initialized:
            if await rag_service.setup():
                # Index server structure if we have a guild
                guild = self.get_guild(config.GUILD_ID) if config.GUILD_ID else None
                if guild:
                    await rag_service.index_server_structure(guild)

        # Start auto learner (scrapes history and learns continuously)
        if config.GUILD_ID and not auto_learner._running:
            if await auto_learner.setup(self, config.GUILD_ID):
                await auto_learner.start()

        # Start style learner (learns owner's communication style)
        if not style_learner._initialized:
            await style_learner.setup()

        # Start feedback learner (tracks corrections and reactions)
        if not feedback_learner._initialized:
            await feedback_learner.setup()

        # Start bump reminder if configured (only once, not on reconnects)
        if config.BUMP_CHANNEL_ID and config.BUMP_ROLE_ID and not bump_service._running:
            bump_service.setup(self, config.BUMP_CHANNEL_ID, config.BUMP_ROLE_ID)
            bump_service.start()

    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        """Handle presence updates."""
        await on_presence_update(self, before, after)

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        await on_message(self, message)
        await self.process_commands(message)

    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        """Handle AutoMod actions - respond when developer ping is blocked."""
        await on_automod_action(self, execution)

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        """Handle reactions to bot messages for feedback learning."""
        # Skip bot reactions
        if user.bot:
            return

        # Check if this is a reaction to a tracked bot message
        message_id = reaction.message.id
        if feedback_learner.is_bot_message(message_id):
            emoji = str(reaction.emoji)
            feedback = feedback_learner.record_reaction(
                message_id=message_id,
                user_id=user.id,
                emoji=emoji,
            )
            if feedback:
                log.tree("Reaction Feedback", [
                    ("User", str(user)),
                    ("Emoji", emoji),
                    ("Type", "Positive" if feedback.is_positive else "Negative"),
                ], emoji="📊")

    async def close(self) -> None:
        """Clean shutdown."""
        log.tree("Shutting Down", [
            ("Bot", str(self.user)),
            ("Reason", "Clean shutdown"),
        ], emoji="🛑")
        auto_learner.stop()
        style_learner.stop()
        feedback_learner.stop()
        bump_service.stop()
        await self.stats_api.stop()
        await http_session.stop()
        await super().close()


# =============================================================================
# Entry Point
# =============================================================================

async def main() -> None:
    """Main entry point."""
    # Set up global exception handlers
    setup_exception_handlers()

    log.tree("Starting TrippixnBot", [
        ("Version", "1.0.0"),
        ("API Port", config.API_PORT),
        ("Guild ID", config.GUILD_ID),
    ], emoji="🚀")

    if not config.TOKEN:
        log.error("TRIPPIXN_BOT_TOKEN environment variable not set")
        return

    # Set up asyncio exception handler
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
