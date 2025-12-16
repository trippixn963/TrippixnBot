"""
TrippixnBot - Translate Command
===============================

Slash command to translate text.

Author: حَـــــنَّـــــا
"""

import discord
from discord import app_commands
from discord.ext import commands

from src.core import config, log
from src.services.translate_service import translate_service, LANGUAGES
from src.views.translate_view import TranslateView, create_translate_embed, send_translate_webhook


# =============================================================================
# Translate Cog
# =============================================================================

class TranslateCog(commands.Cog):
    """Commands for translating text."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="translate",
        description="Translate text to another language"
    )
    @app_commands.describe(
        text="The text to translate",
        to="Target language (e.g., 'ar', 'arabic', 'en', 'english')",
    )
    async def translate(
        self,
        interaction: discord.Interaction,
        text: str,
        to: str = "en",
    ) -> None:
        """Translate text to a target language."""

        await interaction.response.defer()

        log.tree("Translate Command", [
            ("User", str(interaction.user)),
            ("Text", text[:50] + "..." if len(text) > 50 else text),
            ("To", to),
        ], emoji="🌐")

        # Get channel/guild info for webhook
        channel_name = interaction.channel.name if hasattr(interaction.channel, 'name') else str(interaction.channel_id)
        guild_name = interaction.guild.name if interaction.guild else "DM"

        # Perform translation
        result = await translate_service.translate(text, target_lang=to)

        if not result.success:
            embed = discord.Embed(
                title="❌ Translation Failed",
                description=result.error or "An unknown error occurred.",
                color=0xFF0000
            )
            await interaction.followup.send(embed=embed)

            # Send failure webhook
            await send_translate_webhook(
                success=False,
                user=interaction.user,
                source_type="command",
                source_lang="unknown",
                target_lang=to,
                source_name="Unknown",
                target_name=to,
                source_flag="🌐",
                target_flag="🌐",
                original_text=text,
                translated_text="",
                channel_name=channel_name,
                guild_name=guild_name,
                error=result.error,
            )
            return

        # Get developer avatar for footer
        developer_avatar = None
        try:
            developer = await interaction.client.fetch_user(config.OWNER_ID)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
        except Exception:
            pass

        # Build embed with code blocks
        embed = create_translate_embed(result, developer_avatar)

        # Create interactive view
        view = TranslateView(
            original_text=text,
            requester_id=interaction.user.id,
            current_lang=result.target_lang,
            source_lang=result.source_lang,
        )

        msg = await interaction.followup.send(embed=embed, view=view, wait=True)

        log.tree("Translation Sent", [
            ("From", f"{result.source_name} ({result.source_lang})"),
            ("To", f"{result.target_name} ({result.target_lang})"),
            ("User", str(interaction.user)),
        ], emoji="✅")

        # Send success webhook
        await send_translate_webhook(
            success=True,
            user=interaction.user,
            source_type="command",
            source_lang=result.source_lang,
            target_lang=result.target_lang,
            source_name=result.source_name,
            target_name=result.target_name,
            source_flag=result.source_flag,
            target_flag=result.target_flag,
            original_text=result.original_text,
            translated_text=result.translated_text,
            channel_name=channel_name,
            guild_name=guild_name,
            message_jump_url=msg.jump_url if msg else None,
        )

    @app_commands.command(
        name="languages",
        description="Show supported languages for translation"
    )
    async def languages(self, interaction: discord.Interaction) -> None:
        """Show list of supported languages."""

        # Build language list
        lang_list = []
        for code, (name, flag) in sorted(LANGUAGES.items(), key=lambda x: x[1][0]):
            lang_list.append(f"{flag} `{code}` - {name}")

        # Split into columns
        mid = len(lang_list) // 2
        col1 = "\n".join(lang_list[:mid])
        col2 = "\n".join(lang_list[mid:])

        embed = discord.Embed(
            title="🌐 Supported Languages",
            description="Use the language code or name with `/translate`",
            color=0x5865F2
        )
        embed.add_field(name="\u200b", value=col1, inline=True)
        embed.add_field(name="\u200b", value=col2, inline=True)

        await interaction.response.send_message(embed=embed)


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: commands.Bot) -> None:
    """Add the cog to the bot."""
    await bot.add_cog(TranslateCog(bot))
    log.success("Translate command loaded")
