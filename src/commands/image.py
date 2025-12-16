"""
TrippixnBot - Image Command
===========================

Slash command to search for images.

Author: حَـــــنَّـــــا
"""

import discord
from discord import app_commands
from discord.ext import commands

from src.core import config, log
from src.services.image_service import image_service
from src.views.image_view import ImageView


# =============================================================================
# Image Cog
# =============================================================================

class ImageCog(commands.Cog):
    """Commands for searching images."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="image",
        description="Search for images on Google"
    )
    @app_commands.describe(
        query="What to search for",
        safe="SafeSearch level (default: medium)",
    )
    @app_commands.choices(safe=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="High", value="high"),
    ])
    async def image(
        self,
        interaction: discord.Interaction,
        query: str,
        safe: str = "medium",
    ) -> None:
        """Search for images."""
        await interaction.response.defer()

        log.tree("Image Command", [
            ("User", str(interaction.user)),
            ("Query", query),
            ("SafeSearch", safe),
        ], emoji="🖼️")

        # Check if service is available
        if not image_service.is_available:
            embed = discord.Embed(
                title="Image Search Unavailable",
                description="Image search is not configured. Contact the bot owner.",
                color=0xFF0000
            )
            await interaction.followup.send(embed=embed)
            return

        # Search for images
        result = await image_service.search(query, num_results=10, safe_search=safe)

        if not result.success:
            embed = discord.Embed(
                title="Search Failed",
                description=result.error or "An unknown error occurred.",
                color=0xFF0000
            )
            await interaction.followup.send(embed=embed)
            return

        if not result.images:
            embed = discord.Embed(
                title="No Results",
                description=f"No images found for: **{query}**",
                color=0xFFA500
            )
            await interaction.followup.send(embed=embed)
            return

        # Get developer avatar for footer
        developer_avatar = None
        try:
            developer = await interaction.client.fetch_user(config.OWNER_ID)
            developer_avatar = developer.avatar.url if developer and developer.avatar else None
        except Exception:
            pass

        # Create view and embed
        view = ImageView(
            images=result.images,
            query=query,
            requester_id=interaction.user.id,
        )
        embed = view.create_embed(developer_avatar)

        await interaction.followup.send(embed=embed, view=view)

        log.tree("Image Search Sent", [
            ("Query", query),
            ("Results", len(result.images)),
            ("User", str(interaction.user)),
        ], emoji="✅")


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: commands.Bot) -> None:
    """Add the cog to the bot."""
    await bot.add_cog(ImageCog(bot))
    log.success("Image command loaded")
