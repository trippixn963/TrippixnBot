"""
TrippixnBot - Message Handler
=============================

Handles messages and developer ping blocking (only when in DND mode).

Author: حَـــــنَّـــــا
"""

import asyncio
import discord
import aiohttp
from datetime import datetime, timezone
from collections import defaultdict
import time

from src.core import config, log
from src.services import ai_service, stats_store, message_counter, server_intel, rag_service, auto_learner
from src.services.bump_service import bump_service

# Disboard bot ID
DISBOARD_BOT_ID = 302050872383242240


# Lanyard API URL for fetching real-time presence
LANYARD_API_URL = f"https://api.lanyard.rest/v1/users/{config.OWNER_ID}"


# Track user pings: {user_id: [(timestamp, message), ...]}
_ping_history: dict[int, list[tuple[float, str]]] = defaultdict(list)

# AI response cooldown: {user_id: last_response_timestamp}
_ai_cooldowns: dict[int, float] = {}
AI_COOLDOWN_SECONDS = 3600  # 1 hour cooldown between AI responses per user

# =============================================================================
# Multi-Turn Conversation Tracking
# =============================================================================

# Conversation history: {user_id: {"messages": [...], "last_ai_message_id": int, "last_activity": float}}
_conversations: dict[int, dict] = {}
CONVERSATION_TIMEOUT = 900  # 15 minutes - conversations expire after this
CONVERSATION_MAX_TURNS = 6  # Max exchanges to keep in context (3 user + 3 AI)
FOLLOWUP_COOLDOWN = 30  # 30 second cooldown for follow-up messages (shorter than initial)


def _get_conversation(user_id: int) -> dict | None:
    """Get active conversation for user, or None if expired/doesn't exist."""
    if user_id not in _conversations:
        return None

    conv = _conversations[user_id]
    now = time.time()

    # Check if conversation has expired
    if now - conv.get("last_activity", 0) > CONVERSATION_TIMEOUT:
        log.tree("Conversation Expired", [
            ("User ID", str(user_id)),
            ("Inactive For", f"{int((now - conv.get('last_activity', 0)) / 60)}m"),
        ], emoji="⏰")
        del _conversations[user_id]
        return None

    return conv


def _add_to_conversation(user_id: int, role: str, content: str, message_id: int = None) -> None:
    """Add a message to user's conversation history."""
    now = time.time()

    if user_id not in _conversations:
        _conversations[user_id] = {
            "messages": [],
            "last_ai_message_id": None,
            "last_activity": now,
        }

    conv = _conversations[user_id]
    conv["messages"].append({"role": role, "content": content})
    conv["last_activity"] = now

    if role == "assistant" and message_id:
        conv["last_ai_message_id"] = message_id

    # Trim to max turns
    if len(conv["messages"]) > CONVERSATION_MAX_TURNS:
        conv["messages"] = conv["messages"][-CONVERSATION_MAX_TURNS:]

    log.tree("Conversation Updated", [
        ("User ID", str(user_id)),
        ("Role", role),
        ("Total Messages", str(len(conv["messages"]))),
        ("Content Preview", content[:50] + "..." if len(content) > 50 else content),
    ], emoji="💬")


def _clear_conversation(user_id: int) -> None:
    """Clear conversation history for a user."""
    if user_id in _conversations:
        del _conversations[user_id]
        log.tree("Conversation Cleared", [
            ("User ID", str(user_id)),
        ], emoji="🗑️")


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
# Conversation Reply Handler
# =============================================================================

async def _handle_conversation_reply(bot: discord.Client, message: discord.Message) -> None:
    """Handle replies to AI messages for multi-turn conversations."""
    user_id = message.author.id
    replied_to_id = message.reference.message_id

    # Check if user has an active conversation
    conv = _get_conversation(user_id)
    if not conv:
        return  # No active conversation

    # Check if reply is to the bot's last AI message
    if conv.get("last_ai_message_id") != replied_to_id:
        return  # Not replying to our message

    # Check follow-up cooldown (shorter than initial)
    now = time.time()
    last_response = _ai_cooldowns.get(user_id, 0)
    time_since_last = now - last_response

    if time_since_last < FOLLOWUP_COOLDOWN:
        remaining = int(FOLLOWUP_COOLDOWN - time_since_last)
        log.tree("Follow-up Cooldown", [
            ("User", f"{message.author.name} ({message.author.display_name})"),
            ("User ID", str(user_id)),
            ("Remaining", f"{remaining}s"),
        ], emoji="⏳")
        try:
            await message.reply(f"Slow down, wait {remaining}s before replying again.", delete_after=5)
        except Exception:
            pass
        return

    content = message.content.strip()
    if not content:
        return  # Empty message

    user_name = message.author.display_name

    log.tree("Conversation Reply Detected", [
        ("User", f"{message.author.name} ({message.author.display_name})"),
        ("User ID", str(user_id)),
        ("Content", content[:50] + "..." if len(content) > 50 else content),
        ("Conversation Turns", str(len(conv["messages"]))),
    ], emoji="💬")

    # Check if AI service is available
    if not ai_service.is_available:
        log.tree("AI Unavailable", [
            ("User ID", str(user_id)),
            ("Reason", "Service not configured"),
        ], emoji="⚠️")
        return

    # Get developer's current activities for context
    dev_activities = await _get_developer_activity_context()

    # Get RAG context (semantic search)
    rag_context = ""
    if rag_service.is_available:
        rag_context = rag_service.build_context(content, max_tokens=1500)

    # Fallback to basic server context if RAG not available
    if not rag_context:
        rag_context = server_intel.get_server_context()

    # Generate AI response with conversation history
    try:
        async with message.channel.typing():
            response = await ai_service.chat(
                message=content,
                user_name=user_name,
                dev_activity=dev_activities,
                conversation_history=conv["messages"],
                server_context=rag_context,
            )

        if response:
            if len(response) > 2000:
                response = response[:1997] + "..."
                log.tree("Response Truncated", [
                    ("User ID", str(user_id)),
                ], emoji="✂️")

            sent_message = await message.reply(response)

            # Update cooldown
            _ai_cooldowns[user_id] = time.time()

            # Add to conversation history
            _add_to_conversation(user_id, "user", content)
            _add_to_conversation(user_id, "assistant", response, sent_message.id)

            log.tree("Conversation Reply Sent", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("User ID", str(user_id)),
                ("Response Length", str(len(response))),
                ("Total Turns", str(len(conv["messages"]) + 2)),
            ], emoji="✅")
        else:
            log.tree("AI Empty Response", [
                ("User ID", str(user_id)),
            ], emoji="⚠️")

    except discord.Forbidden as e:
        log.tree("Reply Permission Error", [
            ("User ID", str(user_id)),
            ("Error", str(e)[:50]),
        ], emoji="❌")
    except discord.HTTPException as e:
        log.tree("Reply HTTP Error", [
            ("User ID", str(user_id)),
            ("Status", str(e.status)),
            ("Error", str(e)[:50]),
        ], emoji="❌")
    except Exception as e:
        log.error_tree("Conversation Reply Failed", e, [
            ("User ID", str(user_id)),
        ])


# =============================================================================
# Message Handler
# =============================================================================

async def on_message(bot: discord.Client, message: discord.Message) -> None:
    """
    Handle incoming messages.

    Developer pings are blocked by AutoMod when in DND mode.
    Detects replies to AI responses for multi-turn conversations.
    """
    # Check for Disboard bump confirmation (before skipping bots)
    if message.author.id == DISBOARD_BOT_ID:
        # Disboard sends an embed with "Bump done!" when successful
        if message.embeds:
            for embed in message.embeds:
                desc = (embed.description or "").lower()

                if "bump done" in desc:
                    # Record the bump - triggers 2 hour cooldown
                    bump_service.record_bump()
                    break
        return

    if message.author.bot:
        return

    # Increment weekly message counter (only for guild messages)
    if message.guild and message.guild.id == config.GUILD_ID:
        await message_counter.increment()

        # Record message for server intelligence
        server_intel.record_message(message)

        # Auto-learn from message (indexes + extracts FAQs from Q&A patterns)
        await auto_learner.learn_from_message(message)

    # Check for reply to AI response (multi-turn conversation)
    if message.reference and message.reference.message_id:
        await _handle_conversation_reply(bot, message)


# =============================================================================
# AutoMod Action Handler
# =============================================================================

async def on_automod_action(bot: discord.Client, execution: discord.AutoModAction) -> None:
    """
    Handle AutoMod actions - respond with AI when developer ping is blocked.
    """
    # Only respond to keyword triggers (our developer ping rule)
    if execution.rule_trigger_type != discord.AutoModRuleTriggerType.keyword:
        return

    # Get the blocked content
    content = execution.content or ""

    # Check if it contains developer mention
    dev_mentions = [f"<@{config.OWNER_ID}>", f"<@!{config.OWNER_ID}>"]
    if not any(mention in content for mention in dev_mentions):
        return

    log.tree("Developer Ping Intercepted", [
        ("Original Content", content[:50] + "..." if len(content) > 50 else content),
    ], emoji="🎯")

    # Get channel
    channel = bot.get_channel(execution.channel_id)
    if not channel:
        log.warning(f"Could not find channel {execution.channel_id}")
        return

    user_id = execution.user_id
    member = execution.member

    # Check cooldown - 1 hour between AI responses per user
    now = time.time()
    last_response = _ai_cooldowns.get(user_id, 0)
    time_since_last = now - last_response

    if time_since_last < AI_COOLDOWN_SECONDS:
        remaining = int(AI_COOLDOWN_SECONDS - time_since_last)
        remaining_mins = remaining // 60
        remaining_secs = remaining % 60

        log.info(f"User {user_id} on cooldown - {remaining_mins}m {remaining_secs}s remaining")

        try:
            if remaining_mins > 0:
                await channel.send(f"<@{user_id}> Chill, you can ping me again in {remaining_mins}m {remaining_secs}s")
            else:
                await channel.send(f"<@{user_id}> Chill, you can ping me again in {remaining_secs}s")
        except Exception:
            pass
        return

    # Remove developer mention from content
    cleaned_content = content
    for mention in dev_mentions:
        cleaned_content = cleaned_content.replace(mention, "").strip()

    # Default message if empty
    if not cleaned_content:
        cleaned_content = "Hello!"

    user_name = member.display_name if member else "User"

    log.tree("Processing Developer Ping", [
        ("User", user_name),
        ("User ID", user_id),
        ("Cleaned Content", cleaned_content[:100] + "..." if len(cleaned_content) > 100 else cleaned_content),
    ], emoji="🛡️")

    # Check if AI service is available
    if not ai_service.is_available:
        log.warning("AI service not available - cannot respond")
        try:
            await channel.send(f"<@{user_id}> AI service is not available.")
        except Exception as e:
            log.error("Failed to send AI unavailable message", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
        return

    # Get developer's current activities for context
    dev_activities = await _get_developer_activity_context()

    # Get ping history context
    ping_context = _get_ping_context(user_id, cleaned_content)

    # Get RAG context (semantic search) - this replaces the old server_intel approach
    rag_context = ""
    if rag_service.is_available:
        rag_context = rag_service.build_context(cleaned_content, max_tokens=1500)

    # Fallback to basic server context if RAG not available
    server_context = ""
    if not rag_context:
        server_context = server_intel.get_server_context()

    log.tree("Generating AI Response", [
        ("Original Message", content[:80] + "..." if len(content) > 80 else content),
        ("Dev Activity", dev_activities if dev_activities else "None"),
        ("Ping Context", ping_context if ping_context else "First ping"),
        ("RAG Context", "Yes" if rag_context else "No"),
        ("Fallback Context", "Yes" if server_context else "No"),
    ], emoji="🤖")

    # Get existing conversation history (for multi-turn)
    conv = _get_conversation(user_id)
    conversation_history = conv["messages"] if conv else None

    # Generate AI response
    try:
        async with channel.typing():
            response = await ai_service.chat(
                message=cleaned_content,
                user_name=user_name,
                original_blocked=content,
                dev_activity=dev_activities,
                ping_context=ping_context,
                conversation_history=conversation_history,
                server_context=rag_context or server_context,  # RAG context preferred
            )

        if response:
            if len(response) > 2000:
                response = response[:1997] + "..."
                log.tree("Response Truncated", [
                    ("User ID", str(user_id)),
                    ("Original Length", str(len(response))),
                ], emoji="✂️")

            sent_message = await channel.send(f"<@{user_id}> {response}")

            # Update cooldown after successful response
            _ai_cooldowns[user_id] = time.time()

            # Store in conversation history for multi-turn
            _add_to_conversation(user_id, "user", cleaned_content)
            _add_to_conversation(user_id, "assistant", response, sent_message.id)

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
                original_message=cleaned_content,
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
