"""
TrippixnBot - Download Command
==============================

Slash command to download media from Instagram, Twitter/X, and TikTok.

Author: حَـــــنَّـــــا
"""

import discord
from discord import app_commands
from discord.ext import commands

from src.core import log
from src.services.downloader import downloader


# =============================================================================
# Platform Icons
# =============================================================================

PLATFORM_ICONS = {
    "instagram": "📸",
    "twitter": "🐦",
    "tiktok": "🎵",
    "unknown": "📥",
}

PLATFORM_COLORS = {
    "instagram": 0xE4405F,  # Instagram pink
    "twitter": 0x1DA1F2,    # Twitter blue
    "tiktok": 0x000000,     # TikTok black
    "unknown": 0x5865F2,    # Discord blurple
}


# =============================================================================
# Download Cog
# =============================================================================

class DownloadCog(commands.Cog):
    """Commands for downloading social media content."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="download",
        description="Download media from Instagram, Twitter/X, or TikTok"
    )
    @app_commands.describe(url="The URL to download from (Instagram, Twitter/X, or TikTok)")
    async def download(self, interaction: discord.Interaction, url: str) -> None:
        """Download media from a social media URL."""

        # Defer response (shows "thinking...")
        await interaction.response.defer()

        log.tree("Download Command", [
            ("User", str(interaction.user)),
            ("URL", url[:60] + "..." if len(url) > 60 else url),
            ("Channel", str(interaction.channel)),
        ], emoji="📥")

        # Detect platform
        platform = downloader.get_platform(url)

        if not platform:
            embed = discord.Embed(
                title="❌ Unsupported URL",
                description="Only Instagram, Twitter/X, and TikTok URLs are supported.",
                color=0xFF0000
            )
            embed.add_field(
                name="Supported Formats",
                value=(
                    "• `instagram.com/p/...`\n"
                    "• `instagram.com/reel/...`\n"
                    "• `twitter.com/.../status/...`\n"
                    "• `x.com/.../status/...`\n"
                    "• `tiktok.com/@.../video/...`\n"
                    "• `vm.tiktok.com/...`"
                ),
                inline=False
            )
            await interaction.followup.send(embed=embed)
            return

        # Send initial status
        icon = PLATFORM_ICONS.get(platform, "📥")
        status_embed = discord.Embed(
            title=f"{icon} Downloading from {platform.title()}...",
            description="Please wait, this may take a moment.",
            color=PLATFORM_COLORS.get(platform, 0x5865F2)
        )
        status_msg = await interaction.followup.send(embed=status_embed)

        # Download the content
        result = await downloader.download(url)

        if not result.success:
            error_embed = discord.Embed(
                title="❌ Download Failed",
                description=result.error or "An unknown error occurred.",
                color=0xFF0000
            )
            await status_msg.edit(embed=error_embed)
            return

        # Upload files
        try:
            files = []
            total_size = 0
            total_duration = 0.0

            for file_path in result.files:
                file_size = file_path.stat().st_size
                total_size += file_size
                log.tree("Uploading File", [
                    ("File", file_path.name),
                    ("Size", downloader.format_size(file_size)),
                ], emoji="📤")

                # Get duration for videos
                duration = await downloader.get_video_duration(file_path)
                if duration:
                    total_duration += duration

                # Create Discord file
                discord_file = discord.File(file_path, filename=file_path.name)
                files.append(discord_file)

            # Get developer avatar for footer
            developer_avatar = None
            try:
                from src.core import config
                developer = await interaction.client.fetch_user(config.OWNER_ID)
                developer_avatar = developer.avatar.url if developer and developer.avatar else None
            except Exception:
                pass

            # Success embed
            success_embed = discord.Embed(
                title=f"{icon} Downloaded from {platform.title()}",
                color=PLATFORM_COLORS.get(platform, 0x5865F2)
            )
            success_embed.add_field(
                name="Requested By",
                value=f"<@{interaction.user.id}>",
                inline=True
            )
            success_embed.add_field(
                name="Size",
                value=downloader.format_size(total_size),
                inline=True
            )
            if total_duration > 0:
                success_embed.add_field(
                    name="Duration",
                    value=downloader.format_duration(total_duration),
                    inline=True
                )
            success_embed.set_footer(text="Developed By: حَـــــنَّـــــا", icon_url=developer_avatar)

            # Edit original message with embed and upload files
            await status_msg.edit(embed=success_embed, attachments=files)

            log.tree("Upload Complete", [
                ("Files", len(files)),
                ("Platform", platform.title()),
                ("User", str(interaction.user)),
            ], emoji="✅")

        except discord.HTTPException as e:
            log.error("Upload Failed", [
                ("Error", str(e)),
            ])

            error_embed = discord.Embed(
                title="❌ Upload Failed",
                description="The file couldn't be uploaded to Discord. It may be too large.",
                color=0xFF0000
            )
            await status_msg.edit(embed=error_embed)

        finally:
            # Cleanup downloaded files
            if result.files:
                # Get the parent directory (download dir)
                download_dir = result.files[0].parent
                downloader.cleanup([download_dir])


# =============================================================================
# Setup
# =============================================================================

async def setup(bot: commands.Bot) -> None:
    """Add the cog to the bot."""
    await bot.add_cog(DownloadCog(bot))
    log.success("Download command loaded")
