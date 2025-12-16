"""
TrippixnBot - Translate View
============================

Interactive buttons for translation.

Author: حَـــــنَّـــــا
"""

import discord
from discord import ui
from typing import Optional

from src.core import config, log
from src.services.translate_service import translate_service, LANGUAGES


# Quick access buttons config (code, label, emoji)
QUICK_BUTTONS = [
    ("en", "English", "🇬🇧"),
    ("ar", "Arabic", "🇸🇦"),
    ("fr", "French", "🇫🇷"),
    ("de", "German", "🇩🇪"),
]


# =============================================================================
# Language Select Menu
# =============================================================================

class LanguageSelect(ui.Select):
    """Dropdown to select a language for translation."""

    def __init__(self, original_text: str, current_lang: str):
        self.original_text = original_text

        # Build options from common languages (exclude current and quick buttons)
        options = []
        quick_codes = {code for code, _, _ in QUICK_BUTTONS}
        priority_langs = ["es", "it", "pt", "ru", "zh-CN", "ja", "ko", "tr", "nl", "pl", "hi", "he", "fa", "ur", "sv", "el", "cs", "th", "vi"]

        for code in priority_langs:
            if code == current_lang or code in quick_codes:
                continue
            if code in LANGUAGES:
                name, flag = LANGUAGES[code]
                options.append(discord.SelectOption(
                    label=name,
                    value=code,
                    emoji=flag,
                ))
            if len(options) >= 25:  # Discord limit
                break

        super().__init__(
            placeholder="More languages...",
            options=options if options else [discord.SelectOption(label="No more languages", value="none")],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.defer()
            return
        target_lang = self.values[0]
        await self.view.translate_to(interaction, target_lang)


# =============================================================================
# Translate View
# =============================================================================

class TranslateView(ui.View):
    """Interactive view for translation with language buttons."""

    def __init__(
        self,
        original_text: str,
        requester_id: int,
        current_lang: str = "en",
        source_lang: str = "auto",
        timeout: float = 300,  # 5 minutes
    ):
        super().__init__(timeout=timeout)
        self.original_text = original_text
        self.requester_id = requester_id
        self.current_lang = current_lang
        self.source_lang = source_lang

        # Build the view with buttons
        self._rebuild_buttons()

    def _rebuild_buttons(self):
        """Rebuild buttons based on current language."""
        self.clear_items()

        # Add quick translation buttons (skip current language)
        for code, label, emoji in QUICK_BUTTONS:
            if code == self.current_lang:
                continue  # Skip button for current language

            button = ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"translate_{code}",
                row=0,
            )
            button.callback = self._make_button_callback(code)
            self.add_item(button)

        # Add language select dropdown
        self.add_item(LanguageSelect(self.original_text, self.current_lang))

    def _make_button_callback(self, target_lang: str):
        """Create a callback for a language button."""
        async def callback(interaction: discord.Interaction):
            await self.translate_to(interaction, target_lang)
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the requester to use buttons."""
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who requested this translation can use these buttons.",
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for item in self.children:
            item.disabled = True

    async def translate_to(self, interaction: discord.Interaction, target_lang: str):
        """Translate to a new language and update the embed."""
        # Don't re-translate if same language
        if target_lang == self.current_lang:
            await interaction.response.defer()
            return

        await interaction.response.defer()

        log.tree("Re-translating", [
            ("From", self.source_lang),
            ("To", target_lang),
            ("User", str(interaction.user)),
        ], emoji="🌐")

        # Perform translation
        result = await translate_service.translate(
            self.original_text,
            target_lang=target_lang,
            source_lang="auto"  # Always detect from original
        )

        if not result.success:
            await interaction.followup.send(
                f"Translation failed: {result.error}",
                ephemeral=True
            )
            return

        # Update current language
        self.current_lang = target_lang
        self.source_lang = result.source_lang

        # Rebuild buttons (will hide the new current language button)
        self._rebuild_buttons()

        # Get developer avatar for footer
        developer_avatar = None
        try:
            developer = await interaction.client.fetch_user(config.OWNER_ID)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
        except Exception:
            pass

        # Build updated embed
        embed = create_translate_embed(result, developer_avatar)

        await interaction.edit_original_response(embed=embed, view=self)

        log.tree("Re-translation Complete", [
            ("To", f"{result.target_name} ({result.target_lang})"),
            ("User", str(interaction.user)),
        ], emoji="✅")


def create_translate_embed(
    result,
    developer_avatar: Optional[str] = None
) -> discord.Embed:
    """Create a translation embed with code blocks."""
    embed = discord.Embed(
        title=f"{result.source_flag} → {result.target_flag} Translation",
        color=0x5865F2
    )

    # Original text in code block
    original_display = result.original_text
    if len(original_display) > 900:
        original_display = original_display[:897] + "..."
    embed.add_field(
        name=f"Original ({result.source_name})",
        value=f"```\n{original_display}\n```",
        inline=False
    )

    # Translated text in code block
    translated_display = result.translated_text
    if len(translated_display) > 900:
        translated_display = translated_display[:897] + "..."
    embed.add_field(
        name=f"Translation ({result.target_name})",
        value=f"```\n{translated_display}\n```",
        inline=False
    )

    embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar)

    return embed
