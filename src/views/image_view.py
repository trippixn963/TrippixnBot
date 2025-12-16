"""
TrippixnBot - Image View
========================

Interactive view for browsing image search results.

Author: حَـــــنَّـــــا
"""

import discord
from discord import ui
from typing import Optional

from src.core import config, log
from src.services.image_service import ImageResult


# =============================================================================
# Image View
# =============================================================================

class ImageView(ui.View):
    """Interactive view for browsing images with navigation."""

    def __init__(
        self,
        images: list[ImageResult],
        query: str,
        requester_id: int,
        timeout: float = 300,  # 5 minutes
    ):
        super().__init__(timeout=timeout)
        self.images = images
        self.query = query
        self.requester_id = requester_id
        self.current_index = 0

        # Update button states
        self._update_buttons()

    def _update_buttons(self):
        """Update button disabled states based on current index."""
        # First button (<<)
        self.first_button.disabled = self.current_index == 0
        # Previous button (<)
        self.prev_button.disabled = self.current_index == 0
        # Next button (>)
        self.next_button.disabled = self.current_index >= len(self.images) - 1
        # Last button (>>)
        self.last_button.disabled = self.current_index >= len(self.images) - 1

    def create_embed(self, developer_avatar: Optional[str] = None) -> discord.Embed:
        """Create embed for current image."""
        if not self.images:
            return discord.Embed(
                title="No Images Found",
                description=f"No results for: **{self.query}**",
                color=0xFF0000
            )

        image = self.images[self.current_index]

        embed = discord.Embed(
            title=image.title[:256] if len(image.title) > 256 else image.title,
            url=image.source_url,
            color=0x5865F2
        )
        embed.set_image(url=image.url)
        embed.set_footer(
            text=f"Image {self.current_index + 1}/{len(self.images)} • {image.width}x{image.height} • Developed By: حَـــــنَّـــــا",
            icon_url=developer_avatar
        )

        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only allow the requester to use buttons."""
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the person who searched can use these buttons.",
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for item in self.children:
            item.disabled = True

    async def _update_message(self, interaction: discord.Interaction):
        """Update the message with new image."""
        self._update_buttons()

        # Get developer avatar
        developer_avatar = None
        try:
            developer = await interaction.client.fetch_user(config.OWNER_ID)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
        except Exception:
            pass

        embed = self.create_embed(developer_avatar)
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="", emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="first")
    async def first_button(self, interaction: discord.Interaction, button: ui.Button):
        """Go to first image."""
        self.current_index = 0
        await self._update_message(interaction)

    @ui.button(label="", emoji="◀️", style=discord.ButtonStyle.primary, custom_id="prev")
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        """Go to previous image."""
        if self.current_index > 0:
            self.current_index -= 1
        await self._update_message(interaction)

    @ui.button(label="", emoji="▶️", style=discord.ButtonStyle.primary, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        """Go to next image."""
        if self.current_index < len(self.images) - 1:
            self.current_index += 1
        await self._update_message(interaction)

    @ui.button(label="", emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="last")
    async def last_button(self, interaction: discord.Interaction, button: ui.Button):
        """Go to last image."""
        self.current_index = len(self.images) - 1
        await self._update_message(interaction)

    @ui.button(label="", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="delete")
    async def delete_button(self, interaction: discord.Interaction, button: ui.Button):
        """Delete the message."""
        await interaction.message.delete()
