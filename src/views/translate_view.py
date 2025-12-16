"""
TrippixnBot - Translate View
============================

Interactive buttons for translation.

Author: حَـــــنَّـــــا
"""

import discord
import aiohttp
from discord import ui
from typing import Optional
from datetime import datetime, timezone

from src.core import config, log
from src.services.translate_service import translate_service, LANGUAGES


# =============================================================================
# Webhook Logging
# =============================================================================

async def send_translate_webhook(
    success: bool,
    user: discord.User,
    source_type: str,  # "command" or "reply"
    source_lang: str,
    target_lang: str,
    source_name: str,
    target_name: str,
    source_flag: str,
    target_flag: str,
    original_text: str,
    translated_text: str,
    channel_name: str,
    guild_name: str,
    message_jump_url: str = None,
    error: str = None,
) -> None:
    """Send translation log to webhook."""
    if not config.TRANSLATE_WEBHOOK_URL:
        return

    try:
        color = 0x5865F2 if success else 0xFF0000
        status_text = "✅ Success" if success else "❌ Failed"
        source_icon = "💬" if source_type == "reply" else "/"

        embed = {
            "title": f"{source_flag} → {target_flag} Translation {'Completed' if success else 'Failed'}",
            "color": color,
            "fields": [
                {
                    "name": "Status",
                    "value": status_text,
                    "inline": True,
                },
                {
                    "name": "Type",
                    "value": f"{source_icon} {source_type.title()}",
                    "inline": True,
                },
                {
                    "name": "Requested By",
                    "value": f"**{user.display_name}** (`{user.id}`)",
                    "inline": True,
                },
                {
                    "name": "Languages",
                    "value": f"{source_flag} {source_name} → {target_flag} {target_name}",
                    "inline": True,
                },
                {
                    "name": "Server",
                    "value": guild_name,
                    "inline": True,
                },
                {
                    "name": "Channel",
                    "value": f"#{channel_name}",
                    "inline": True,
                },
            ],
            "thumbnail": {"url": user.display_avatar.url} if user.display_avatar else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "TrippixnBot Translation Logs"},
        }

        # Add original text (truncated)
        original_display = original_text[:500] + "..." if len(original_text) > 500 else original_text
        embed["fields"].append({
            "name": f"Original ({source_name})",
            "value": f"```\n{original_display}\n```",
            "inline": False,
        })

        # Add translated text if success
        if success and translated_text:
            translated_display = translated_text[:500] + "..." if len(translated_text) > 500 else translated_text
            embed["fields"].append({
                "name": f"Translation ({target_name})",
                "value": f"```\n{translated_display}\n```",
                "inline": False,
            })

        # Add message link if available
        if message_jump_url:
            embed["fields"].append({
                "name": "View Translation",
                "value": f"[Jump to Message]({message_jump_url})",
                "inline": False,
            })

        # Add error if failed
        if not success and error:
            embed["fields"].append({
                "name": "Error",
                "value": error[:500],
                "inline": False,
            })

        # Remove None thumbnail
        if not embed.get("thumbnail", {}).get("url"):
            embed.pop("thumbnail", None)

        async with aiohttp.ClientSession() as session:
            payload = {"embeds": [embed]}
            async with session.post(config.TRANSLATE_WEBHOOK_URL, json=payload) as resp:
                if resp.status in (200, 204):
                    log.info("Translation webhook sent")
                else:
                    log.warning(f"Translation webhook returned status {resp.status}")

    except Exception as e:
        log.error("Failed to send translation webhook", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])


# Priority languages for quick buttons (will show top 4 excluding current)
PRIORITY_LANGUAGES = [
    ("en", "English", "🇬🇧"),
    ("ar", "Arabic", "🇸🇦"),
    ("fr", "French", "🇫🇷"),
    ("de", "German", "🇩🇪"),
    ("es", "Spanish", "🇪🇸"),
    ("ru", "Russian", "🇷🇺"),
    ("tr", "Turkish", "🇹🇷"),
    ("zh-CN", "Chinese", "🇨🇳"),
]


# =============================================================================
# Language Select Menu
# =============================================================================

class LanguageSelect(ui.Select):
    """Dropdown to select a language for translation."""

    def __init__(self, original_text: str, current_lang: str, shown_buttons: set[str]):
        self.original_text = original_text

        # Build options from all languages (exclude current and shown buttons)
        options = []
        # Additional languages not in priority list
        extra_langs = ["it", "pt", "ja", "ko", "nl", "pl", "hi", "he", "fa", "ur", "sv", "el", "cs", "th", "vi", "id", "uk", "ro", "hu", "da", "no", "fi", "ms"]

        # First add priority languages that aren't shown as buttons
        for code, label, emoji in PRIORITY_LANGUAGES:
            if code == current_lang or code in shown_buttons:
                continue
            options.append(discord.SelectOption(
                label=label,
                value=code,
                emoji=emoji,
            ))

        # Then add extra languages
        for code in extra_langs:
            if code == current_lang:
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

        # Add top 4 quick translation buttons (excluding current language)
        shown_buttons = set()
        button_count = 0
        for code, label, emoji in PRIORITY_LANGUAGES:
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
            shown_buttons.add(code)

            button_count += 1
            if button_count >= 4:
                break  # Only show 4 buttons

        # Add language select dropdown (exclude languages shown as buttons)
        self.add_item(LanguageSelect(self.original_text, self.current_lang, shown_buttons))

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
