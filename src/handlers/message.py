"""
TrippixnBot - Message Handler
=============================

Handles AutoMod blocked messages - responds with AI when someone tries to ping developer.

Author: حَـــــنَّـــــا
"""

import asyncio
import discord
import aiohttp
import re
from datetime import datetime, timezone
from collections import defaultdict
import time

from src.core import config, log
from src.services import ai_service, stats_store
from src.services.downloader import downloader
from src.services.translate_service import translate_service
from src.views.translate_view import TranslateView, create_translate_embed


# Lanyard API URL for fetching real-time presence
LANYARD_API_URL = f"https://api.lanyard.rest/v1/users/{config.OWNER_ID}"


# Track user pings: {user_id: [(timestamp, message), ...]}
_ping_history: dict[int, list[tuple[float, str]]] = defaultdict(list)


def _get_ping_context(user_id: int, current_message: str) -> str:
    """Get context about how many times this user has pinged recently."""
    now = time.time()

    # Get count before cleaning
    old_count = len(_ping_history[user_id])

    # Clean old pings
    _ping_history[user_id] = [
        (ts, msg) for ts, msg in _ping_history[user_id]
        if now - ts < config.PING_HISTORY_WINDOW
    ]

    cleaned_count = old_count - len(_ping_history[user_id])
    if cleaned_count > 0:
        log.info(f"Cleaned {cleaned_count} old pings for user {user_id}")

    # Get count before adding current
    recent_pings = len(_ping_history[user_id])

    # Add current ping
    _ping_history[user_id].append((now, current_message))

    log.tree("Ping History", [
        ("User ID", user_id),
        ("Previous Pings (1h)", recent_pings),
        ("Current Ping #", recent_pings + 1),
        ("Total Tracked Users", len(_ping_history)),
    ], emoji="📊")

    if recent_pings == 0:
        return ""
    elif recent_pings == 1:
        log.info(f"User {user_id} is pinging for the 2nd time in an hour")
        return "This user pinged you once before in the last hour. They're pinging again."
    elif recent_pings == 2:
        log.warning(f"User {user_id} is pinging for the 3rd time in an hour - getting annoying")
        return f"This user has pinged you {recent_pings} times in the last hour. This is their 3rd ping. They're being annoying."
    else:
        log.warning(f"User {user_id} is pinging for the {recent_pings + 1}th time in an hour - spam")
        return f"This user has pinged you {recent_pings} times in the last hour. This is ping #{recent_pings + 1}. Tell them to chill."


async def _get_developer_activity_context() -> str:
    """Get developer's current activity from Lanyard API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(LANYARD_API_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    log.warning(f"Lanyard API returned status {resp.status}")
                    return ""

                data = await resp.json()

        if not data.get("success"):
            return ""

        lanyard = data.get("data", {})
        status = lanyard.get("discord_status", "offline")
        activities = lanyard.get("activities", [])
        spotify = lanyard.get("spotify")

        context_parts = []

        # Check Spotify first (Lanyard has a dedicated spotify field)
        if spotify:
            artist = spotify.get("artist", "")
            if artist:
                context_parts.append(f"listening to {artist}")
            else:
                context_parts.append("listening to music")

        # Check other activities
        for activity in activities:
            activity_type = activity.get("type", 0)
            name = activity.get("name", "")

            # Skip Spotify activity (already handled above) and custom status
            if name == "Spotify" or activity_type == 4:
                continue

            if activity_type == 0:  # Playing
                if "Visual Studio Code" in name or "VS Code" in name or "Code" == name:
                    context_parts.append("coding in VS Code")
                elif "IntelliJ" in name or "PyCharm" in name or "WebStorm" in name:
                    context_parts.append(f"coding in {name}")
                else:
                    context_parts.append(f"playing {name}")
            elif activity_type == 1:  # Streaming
                context_parts.append(f"streaming {name}")
            elif activity_type == 2:  # Listening (non-Spotify)
                context_parts.append(f"listening to {name}")
            elif activity_type == 3:  # Watching
                context_parts.append(f"watching {name}")
            elif activity_type == 5:  # Competing
                context_parts.append(f"competing in {name}")

        if context_parts:
            return "He's currently " + " and ".join(context_parts) + "."

        # No activities, check status
        if status == "dnd":
            return "He's currently set to Do Not Disturb."
        elif status == "idle":
            return "He's currently idle/away."
        elif status == "offline":
            return "He's currently offline."

        return ""

    except asyncio.TimeoutError:
        log.warning("Lanyard API request timed out")
        return ""
    except Exception as e:
        log.warning(f"Failed to get developer activity from Lanyard: {e}")
        return ""


# =============================================================================
# Reply Download Handler (Owner Only)
# =============================================================================

# Platform styling (same as download command)
PLATFORM_ICONS = {
    "instagram": "📸",
    "twitter": "🐦",
    "tiktok": "🎵",
    "unknown": "📥",
}

PLATFORM_COLORS = {
    "instagram": 0xE4405F,
    "twitter": 0x1DA1F2,
    "tiktok": 0x000000,
    "unknown": 0x5865F2,
}


async def _send_download_webhook(
    success: bool,
    user: discord.User,
    platform: str,
    url: str,
    channel_name: str,
    guild_name: str,
    file_count: int = 0,
    total_size: int = 0,
    total_duration: float = 0,
    media_jump_url: str = None,
    error: str = None,
) -> None:
    """Send download log to webhook."""
    if not config.DOWNLOAD_WEBHOOK_URL:
        return

    try:
        icon = PLATFORM_ICONS.get(platform, "📥")
        color = 0x00FF00 if success else 0xFF0000
        status_text = "✅ Success" if success else "❌ Failed"

        embed = {
            "title": f"{icon} Download {'Completed' if success else 'Failed'}",
            "color": color,
            "fields": [
                {
                    "name": "Status",
                    "value": status_text,
                    "inline": True,
                },
                {
                    "name": "Platform",
                    "value": platform.title(),
                    "inline": True,
                },
                {
                    "name": "Requested By",
                    "value": f"**{user.display_name}** (`{user.id}`)",
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
                {
                    "name": "Source",
                    "value": f"[Original Link]({url})",
                    "inline": True,
                },
            ],
            "thumbnail": {"url": user.display_avatar.url} if user.display_avatar else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "TrippixnBot Download Logs"},
        }

        # Add media info if successful
        if success:
            if file_count > 0:
                embed["fields"].append({
                    "name": "Files",
                    "value": str(file_count),
                    "inline": True,
                })
            if total_size > 0:
                embed["fields"].append({
                    "name": "Size",
                    "value": downloader.format_size(total_size),
                    "inline": True,
                })
            if total_duration > 0:
                embed["fields"].append({
                    "name": "Duration",
                    "value": downloader.format_duration(total_duration),
                    "inline": True,
                })
            if media_jump_url:
                embed["fields"].append({
                    "name": "View Media",
                    "value": f"[Jump to Message]({media_jump_url})",
                    "inline": False,
                })

        # Add error if failed
        if not success and error:
            embed["fields"].append({
                "name": "Error",
                "value": error[:1000],
                "inline": False,
            })

        # Remove None thumbnail
        if not embed.get("thumbnail", {}).get("url"):
            embed.pop("thumbnail", None)

        async with aiohttp.ClientSession() as session:
            payload = {"embeds": [embed]}
            async with session.post(config.DOWNLOAD_WEBHOOK_URL, json=payload) as resp:
                if resp.status in (200, 204):
                    log.info("Download webhook sent")
                else:
                    log.warning(f"Download webhook returned status {resp.status}")

    except Exception as e:
        log.error("Failed to send download webhook", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])


async def _handle_reply_download(message: discord.Message) -> None:
    """Handle replying 'download' to a message with a link."""
    log.tree("Reply Download Triggered", [
        ("User", f"{message.author} ({message.author.id})"),
        ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else str(message.channel.id)),
        ("Message ID", message.id),
    ], emoji="📥")

    # Get the referenced message
    ref = message.reference
    if not ref or not ref.message_id:
        log.warning("No message reference found")
        return

    log.info(f"Fetching referenced message {ref.message_id}")

    try:
        # Fetch the original message
        original = await message.channel.fetch_message(ref.message_id)
        log.tree("Original Message Found", [
            ("Author", f"{original.author} ({original.author.id})"),
            ("Content Length", len(original.content) if original.content else 0),
        ], emoji="📄")
    except discord.NotFound:
        log.warning(f"Referenced message {ref.message_id} not found")
        await message.reply("Couldn't find that message.", mention_author=False)
        return
    except discord.Forbidden:
        log.warning(f"No permission to read message {ref.message_id}")
        await message.reply("No permission to read that message.", mention_author=False)
        return

    # Extract URL from the original message
    content = original.content
    if not content:
        log.warning("Original message has no text content")
        await message.reply("That message has no text content.", mention_author=False)
        return

    # Find URLs in the message
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, content)
    log.info(f"Found {len(urls)} URL(s) in message")

    if not urls:
        log.warning("No URLs found in message")
        await message.reply("No URL found in that message.", mention_author=False)
        return

    # Find first supported URL
    supported_url = None
    platform = None
    for url in urls:
        detected_platform = downloader.get_platform(url)
        log.info(f"URL: {url[:50]}... -> Platform: {detected_platform or 'unsupported'}")
        if detected_platform:
            platform = detected_platform
            supported_url = url
            break

    if not supported_url:
        log.warning("No supported platform URL found")
        await message.reply("No supported URL found (Instagram, Twitter/X, TikTok).", mention_author=False)
        return

    log.tree("Starting Download", [
        ("Platform", platform.title()),
        ("URL", supported_url[:60] + "..." if len(supported_url) > 60 else supported_url),
        ("Requested By", str(message.author)),
    ], emoji="⬇️")

    # Send status message
    icon = PLATFORM_ICONS.get(platform, "📥")
    status_embed = discord.Embed(
        title=f"{icon} Downloading from {platform.title()}...",
        description="Please wait, this may take a moment.",
        color=PLATFORM_COLORS.get(platform, 0x5865F2)
    )
    status_msg = await message.reply(embed=status_embed, mention_author=False)
    log.info(f"Status message sent: {status_msg.id}")

    # Download
    log.info("Calling downloader service...")
    result = await downloader.download(supported_url)

    # Get channel/guild info for webhook
    channel_name = message.channel.name if hasattr(message.channel, 'name') else str(message.channel.id)
    guild_name = message.guild.name if message.guild else "DM"

    if not result.success:
        log.error("Download Failed", [
            ("Platform", platform.title()),
            ("Error", result.error or "Unknown error"),
        ])
        error_embed = discord.Embed(
            title="❌ Download Failed",
            description=result.error or "An unknown error occurred.",
            color=0xFF0000
        )
        await status_msg.edit(embed=error_embed)

        # Send failure webhook
        await _send_download_webhook(
            success=False,
            user=message.author,
            platform=platform,
            url=supported_url,
            channel_name=channel_name,
            guild_name=guild_name,
            error=result.error,
        )
        return

    log.tree("Download Successful", [
        ("Files", len(result.files)),
        ("Platform", platform.title()),
    ], emoji="✅")

    # Upload files
    upload_success = False
    try:
        files = []
        total_size = 0
        total_duration = 0.0

        for file_path in result.files:
            file_size = file_path.stat().st_size
            total_size += file_size

            # Get duration for videos
            duration = await downloader.get_video_duration(file_path)
            if duration:
                total_duration += duration

            log.tree("Preparing File", [
                ("File", file_path.name),
                ("Size", downloader.format_size(file_size)),
                ("Duration", downloader.format_duration(duration) if duration else "N/A"),
            ], emoji="📤")

            discord_file = discord.File(file_path, filename=file_path.name)
            files.append(discord_file)

        # Get developer avatar for footer
        developer_avatar = None
        try:
            developer = await message.guild.fetch_member(config.OWNER_ID)
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
            value=f"<@{message.author.id}>",
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

        # Send the media as a new message (so it stays when we delete others)
        log.info("Uploading media to Discord...")
        media_msg = await message.channel.send(embed=success_embed, files=files)
        log.info(f"Media uploaded successfully: {media_msg.id}")
        upload_success = True

        log.tree("Upload Complete", [
            ("Files", len(files)),
            ("Total Size", downloader.format_size(total_size)),
            ("Duration", downloader.format_duration(total_duration) if total_duration > 0 else "N/A"),
            ("Media Message ID", media_msg.id),
        ], emoji="✅")

        # Send success webhook with jump link to media
        await _send_download_webhook(
            success=True,
            user=message.author,
            platform=platform,
            url=supported_url,
            channel_name=channel_name,
            guild_name=guild_name,
            file_count=len(result.files),
            total_size=total_size,
            total_duration=total_duration,
            media_jump_url=media_msg.jump_url,
        )

        # Clean up: Delete status message, download reply, and original message
        log.info("Cleaning up messages...")

        # Delete status message (the "Downloading..." message)
        try:
            await status_msg.delete()
            log.info(f"Deleted status message: {status_msg.id}")
        except discord.HTTPException as e:
            log.warning(f"Failed to delete status message: {e}")

        # Delete the "download" reply message
        try:
            await message.delete()
            log.info(f"Deleted download reply: {message.id}")
        except discord.HTTPException as e:
            log.warning(f"Failed to delete download reply: {e}")

        # Delete the original message with the link
        try:
            await original.delete()
            log.info(f"Deleted original message: {original.id}")
        except discord.HTTPException as e:
            log.warning(f"Failed to delete original message: {e}")

        log.tree("Reply Download Complete", [
            ("Platform", platform.title()),
            ("Files", len(result.files)),
            ("Requested By", str(message.author)),
            ("Messages Cleaned", "Yes"),
        ], emoji="🎉")

    except discord.HTTPException as e:
        log.error("Upload Failed", [
            ("Error Type", type(e).__name__),
            ("Status", getattr(e, 'status', 'N/A')),
            ("Message", str(e)),
        ])
        error_embed = discord.Embed(
            title="❌ Upload Failed",
            description="The file couldn't be uploaded to Discord. It may be too large.",
            color=0xFF0000
        )
        await status_msg.edit(embed=error_embed)

        # Send upload failure webhook
        await _send_download_webhook(
            success=False,
            user=message.author,
            platform=platform,
            url=supported_url,
            channel_name=channel_name,
            guild_name=guild_name,
            error=f"Upload failed: {str(e)}",
        )

    finally:
        # Cleanup downloaded files
        if result.files:
            download_dir = result.files[0].parent
            downloader.cleanup([download_dir])
            log.info(f"Cleaned up temp directory: {download_dir}")


# =============================================================================
# Reply Translate Handler
# =============================================================================

async def _handle_reply_translate(message: discord.Message, target_lang: str = "en") -> None:
    """Handle replying 'translate' or 'tr' to a message."""
    log.tree("Reply Translate Triggered", [
        ("User", f"{message.author} ({message.author.id})"),
        ("Channel", f"#{message.channel.name}" if hasattr(message.channel, 'name') else str(message.channel.id)),
        ("Target Lang", target_lang),
    ], emoji="🌐")

    # Get the referenced message
    ref = message.reference
    if not ref or not ref.message_id:
        log.warning("No message reference found")
        return

    try:
        # Fetch the original message
        original = await message.channel.fetch_message(ref.message_id)
    except discord.NotFound:
        await message.reply("Couldn't find that message.", mention_author=False)
        return
    except discord.Forbidden:
        await message.reply("No permission to read that message.", mention_author=False)
        return

    # Get text to translate
    text = original.content
    if not text:
        await message.reply("That message has no text content.", mention_author=False)
        return

    # Perform translation
    result = await translate_service.translate(text, target_lang=target_lang)

    if not result.success:
        embed = discord.Embed(
            title="❌ Translation Failed",
            description=result.error or "An unknown error occurred.",
            color=0xFF0000
        )
        await message.reply(embed=embed, mention_author=False)
        return

    # Get developer avatar for footer
    developer_avatar = None
    try:
        developer = await message.guild.fetch_member(config.OWNER_ID)
        developer_avatar = developer.avatar.url if developer and developer.avatar else None
    except Exception:
        pass

    # Build embed with code blocks
    embed = create_translate_embed(result, developer_avatar)

    # Create interactive view (only requester can use buttons)
    view = TranslateView(
        original_text=text,
        requester_id=message.author.id,
        current_lang=result.target_lang,
        source_lang=result.source_lang,
    )

    await message.reply(embed=embed, view=view, mention_author=False)

    log.tree("Reply Translate Complete", [
        ("From", f"{result.source_name} ({result.source_lang})"),
        ("To", f"{result.target_name} ({result.target_lang})"),
        ("User", str(message.author)),
    ], emoji="✅")


def _parse_translate_command(content: str) -> tuple[bool, str]:
    """
    Parse translate/tr command from message content.

    Returns:
        (is_translate_command, target_language)
    """
    content = content.lower().strip()

    # "translate" or "tr" alone -> default to English
    if content in ("translate", "tr"):
        return (True, "en")

    # "translate ar" or "tr arabic" etc.
    parts = content.split(None, 1)
    if len(parts) == 2 and parts[0] in ("translate", "tr"):
        lang = parts[1].strip()
        # Validate language
        resolved = translate_service.resolve_language(lang)
        if resolved:
            return (True, resolved)
        # Invalid language, still a translate command but return default
        return (True, "en")

    return (False, "")


# =============================================================================
# Message Handler
# =============================================================================

async def on_message(bot: discord.Client, message: discord.Message) -> None:
    """
    Handle incoming messages.

    Developer pings are blocked by AutoMod before reaching here.
    """
    if message.author.bot:
        return

    # Check if message is a reply
    if message.reference:
        content = message.content.lower().strip()

        # Reply-to-download feature
        if content == "download":
            await _handle_reply_download(message)
            return

        # Reply-to-translate feature
        is_translate, target_lang = _parse_translate_command(message.content)
        if is_translate:
            await _handle_reply_translate(message, target_lang)
            return


# =============================================================================
# AutoMod Action Handler
# =============================================================================

async def on_automod_action(bot: discord.Client, execution: discord.AutoModAction) -> None:
    """
    Handle AutoMod actions - respond with AI when developer ping is blocked.
    """
    log.tree("AutoMod Action Received", [
        ("Rule ID", execution.rule_id),
        ("Trigger Type", execution.rule_trigger_type.name if execution.rule_trigger_type else "Unknown"),
        ("Action Type", execution.action.type.name if execution.action else "Unknown"),
        ("User ID", execution.user_id),
        ("Channel ID", execution.channel_id),
        ("Content", (execution.content[:50] + "...") if execution.content and len(execution.content) > 50 else execution.content),
    ], emoji="📥")

    # Only respond to keyword triggers (our developer ping rule)
    if execution.rule_trigger_type != discord.AutoModRuleTriggerType.keyword:
        log.info(f"Ignoring AutoMod action - not keyword trigger (was {execution.rule_trigger_type})")
        return

    # Get the blocked content
    content = execution.content or ""

    # Check if it contains developer mention
    dev_mentions = [f"<@{config.OWNER_ID}>", f"<@!{config.OWNER_ID}>"]
    if not any(mention in content for mention in dev_mentions):
        log.info(f"Ignoring AutoMod action - no developer mention in content")
        return

    log.tree("Developer Ping Intercepted", [
        ("Original Content", content),
    ], emoji="🎯")

    # Get channel
    channel = bot.get_channel(execution.channel_id)
    if not channel:
        log.warning(f"Could not find channel {execution.channel_id}")
        return

    log.tree("Channel Found", [
        ("Channel", f"#{channel.name}" if hasattr(channel, 'name') else str(channel)),
        ("Channel ID", execution.channel_id),
    ], emoji="📍")

    user_id = execution.user_id
    member = execution.member

    # Remove developer mention from content
    for mention in dev_mentions:
        content = content.replace(mention, "").strip()

    # Default message if empty
    if not content:
        content = "Hello!"

    user_name = member.display_name if member else "User"

    log.tree("Processing Developer Ping", [
        ("User", user_name),
        ("User ID", user_id),
        ("Cleaned Content", content[:100] + "..." if len(content) > 100 else content),
        ("Has Member", "Yes" if member else "No"),
    ], emoji="🛡️")

    # Check if AI service is available
    if not ai_service.is_available:
        log.warning("AI service not available - cannot respond")
        try:
            await channel.send(f"<@{user_id}> AI service is not available.")
            log.info("Sent AI unavailable message")
        except Exception as e:
            log.error("Failed to send AI unavailable message", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
        return

    # Store original blocked message for footer display
    original_blocked = execution.content or ""

    # Get developer's current activities for context
    dev_activities = await _get_developer_activity_context()

    # Get ping history context
    ping_context = _get_ping_context(user_id, content)

    log.tree("Generating AI Response", [
        ("Original Blocked", original_blocked[:80] + "..." if len(original_blocked) > 80 else original_blocked),
        ("Dev Activity", dev_activities if dev_activities else "None"),
        ("Ping Context", ping_context if ping_context else "First ping"),
    ], emoji="🤖")

    # Generate AI response
    try:
        async with channel.typing():
            response = await ai_service.chat(
                message=content,
                user_name=user_name,
                original_blocked=original_blocked,
                dev_activity=dev_activities,
                ping_context=ping_context,
            )

        if response:
            if len(response) > 2000:
                response = response[:1997] + "..."
                log.info("Response truncated to 2000 chars")

            sent_message = await channel.send(f"<@{user_id}> {response}")

            log.tree("AI Response Sent", [
                ("To User", user_name),
                ("Response Length", len(response)),
                ("Channel", f"#{channel.name}" if hasattr(channel, 'name') else str(channel)),
            ], emoji="✅")

            # Send webhook notification
            user_avatar = member.display_avatar.url if member else None
            channel_name = channel.name if hasattr(channel, 'name') else str(channel)
            guild_id = execution.guild_id

            await _send_ping_notification(
                user_name=user_name,
                user_id=user_id,
                user_avatar=user_avatar,
                original_message=content,
                ai_response=response,
                channel_name=channel_name,
                channel_id=execution.channel_id,
                guild_id=guild_id,
                response_message_id=sent_message.id,
            )
        else:
            await channel.send(f"<@{user_id}> Sorry, I couldn't generate a response.")
            log.warning("AI returned empty response")

    except discord.Forbidden as e:
        log.error("Permission Error sending response", [
            ("Error", str(e)),
            ("Channel", execution.channel_id),
        ])
    except discord.HTTPException as e:
        log.error("HTTP Error sending response", [
            ("Status", e.status),
            ("Error", str(e)),
        ])
    except Exception as e:
        log.error("Failed to send AI response", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])


async def _send_ping_notification(
    user_name: str,
    user_id: int,
    user_avatar: str,
    original_message: str,
    ai_response: str,
    channel_name: str,
    channel_id: int,
    guild_id: int,
    response_message_id: int,
) -> None:
    """Send webhook notification about developer ping."""
    try:
        # Create jump link to the AI response
        jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{response_message_id}"

        # Truncate response for embed if too long
        display_response = ai_response
        if len(display_response) > 1000:
            display_response = display_response[:997] + "..."

        embed = {
            "title": "🔔 Someone tried to ping you",
            "color": 0x5865F2,  # Discord blurple
            "fields": [
                {
                    "name": "User",
                    "value": f"**{user_name}** (`{user_id}`)",
                    "inline": True,
                },
                {
                    "name": "Channel",
                    "value": f"#{channel_name}",
                    "inline": True,
                },
                {
                    "name": "Their Message",
                    "value": original_message or "*Empty ping*",
                    "inline": False,
                },
                {
                    "name": "AI Response",
                    "value": display_response,
                    "inline": False,
                },
                {
                    "name": "Jump to Conversation",
                    "value": f"[Click here]({jump_url})",
                    "inline": False,
                },
            ],
            "thumbnail": {"url": user_avatar} if user_avatar else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "TrippixnBot Ping Notification"},
        }

        # Remove None thumbnail if no avatar
        if not user_avatar:
            del embed["thumbnail"]

        payload = {"embeds": [embed]}

        async with aiohttp.ClientSession() as session:
            async with session.post(config.PING_WEBHOOK_URL, json=payload) as resp:
                if resp.status == 204:
                    log.info("Ping notification sent to webhook")
                else:
                    log.warning(f"Webhook returned status {resp.status}")

    except Exception as e:
        log.error("Failed to send ping notification", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])
