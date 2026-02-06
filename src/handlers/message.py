"""
TrippixnBot - Message Handler
=============================

Handles message counting for stats.

Author: حَـــــنَّـــــا
"""

import discord

from src.core import config
from src.services import message_counter


async def on_message(bot: discord.Client, message: discord.Message) -> None:
    """
    Handle incoming messages.

    Counts messages for stats tracking.
    """
    if message.author.bot:
        return

    # Only count messages from main guild
    if not message.guild or message.guild.id != config.GUILD_ID:
        return

    # Increment message counter
    await message_counter.increment()
