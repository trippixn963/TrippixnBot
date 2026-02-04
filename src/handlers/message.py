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
from src.services.feedback_learner import feedback_learner
from src.services.user_memory import user_memory


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

# Conversation history: {user_id: {"messages": [...], "last_ai_message_id": int, "last_activity": float, "followup_used": bool}}
_conversations: dict[int, dict] = {}
CONVERSATION_TIMEOUT = 900  # 15 minutes - conversations expire after this
CONVERSATION_MAX_TURNS = 6  # Max exchanges to keep in context (3 user + 3 AI)
FOLLOWUP_COOLDOWN = 30  # 30 second cooldown for follow-up messages (shorter than initial)
MAX_FOLLOWUPS = 1  # Only allow 1 follow-up reply before requiring full cooldown

# =============================================================================
# Memory Management
# =============================================================================

MAX_TRACKED_USERS = 500  # Max users to track in memory
CLEANUP_INTERVAL = 300  # Run cleanup every 5 minutes
_last_cleanup = 0


def _cleanup_memory() -> None:
    """
    Periodic cleanup to prevent memory leaks.
    Removes old/stale entries from all tracking dicts.
    """
    global _last_cleanup
    now = time.time()

    # Only run cleanup every CLEANUP_INTERVAL seconds
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    cleaned = {"pings": 0, "cooldowns": 0, "conversations": 0}

    # Clean ping history - remove users with no recent pings
    users_to_remove = []
    for user_id, pings in _ping_history.items():
        # Filter old pings
        fresh_pings = [(ts, msg) for ts, msg in pings if now - ts < config.PING_HISTORY_WINDOW]
        if fresh_pings:
            _ping_history[user_id] = fresh_pings
        else:
            users_to_remove.append(user_id)

    for user_id in users_to_remove:
        del _ping_history[user_id]
        cleaned["pings"] += 1

    # Clean cooldowns - remove expired entries (older than 2 hours)
    expired_cooldowns = [
        user_id for user_id, ts in _ai_cooldowns.items()
        if now - ts > AI_COOLDOWN_SECONDS * 2
    ]
    for user_id in expired_cooldowns:
        del _ai_cooldowns[user_id]
        cleaned["cooldowns"] += 1

    # Clean conversations - remove expired
    expired_convos = [
        user_id for user_id, conv in _conversations.items()
        if now - conv.get("last_activity", 0) > CONVERSATION_TIMEOUT
    ]
    for user_id in expired_convos:
        del _conversations[user_id]
        cleaned["conversations"] += 1

    # If still too many entries, evict oldest
    if len(_ai_cooldowns) > MAX_TRACKED_USERS:
        sorted_cooldowns = sorted(_ai_cooldowns.items(), key=lambda x: x[1])
        to_evict = len(_ai_cooldowns) - MAX_TRACKED_USERS
        for user_id, _ in sorted_cooldowns[:to_evict]:
            del _ai_cooldowns[user_id]
            cleaned["cooldowns"] += 1

    total_cleaned = sum(cleaned.values())
    if total_cleaned > 0:
        log.tree("Memory Cleanup", [
            ("Pings Removed", str(cleaned["pings"])),
            ("Cooldowns Removed", str(cleaned["cooldowns"])),
            ("Conversations Removed", str(cleaned["conversations"])),
            ("Ping Users", str(len(_ping_history))),
            ("Cooldown Users", str(len(_ai_cooldowns))),
            ("Active Convos", str(len(_conversations))),
        ], emoji="🧹")


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
            "followup_count": 0,
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
# Enhanced Context Functions
# =============================================================================

def _get_time_context() -> str:
    """Get time-aware context for AI responses."""
    from datetime import datetime
    import pytz

    # Use EST timezone (server timezone)
    try:
        tz = pytz.timezone("America/New_York")
        now = datetime.now(tz)
    except Exception:
        now = datetime.now()

    hour = now.hour
    time_str = now.strftime("%I:%M %p")

    if 0 <= hour < 5:
        log.tree("Time Context Applied", [
            ("Time", time_str),
            ("Period", "Late Night (12am-5am)"),
            ("Mood", "Extra grumpy"),
        ], emoji="🌙")
        return "TIME CONTEXT: It's very late at night (midnight to 5am). You're probably tired/sleeping. Be extra grumpy about being pinged at this hour."
    elif 5 <= hour < 8:
        log.tree("Time Context Applied", [
            ("Time", time_str),
            ("Period", "Early Morning (5am-8am)"),
            ("Mood", "Groggy/annoyed"),
        ], emoji="🌅")
        return "TIME CONTEXT: It's early morning (5-8am). You might be just waking up or still sleeping. Can be groggy/annoyed."
    elif 22 <= hour < 24:
        log.tree("Time Context Applied", [
            ("Time", time_str),
            ("Period", "Late Evening (10pm-12am)"),
            ("Mood", "Winding down"),
        ], emoji="🌃")
        return "TIME CONTEXT: It's late night (10pm-midnight). You're probably winding down. Can mention you're about to sleep if relevant."
    else:
        return ""  # Normal hours, no special context


async def _classify_ping_intent(message: str) -> str:
    """
    Classify the intent behind a ping using keywords.

    Returns context string about the intent.
    """
    msg_lower = message.lower()

    # Question indicators
    question_words = ["how", "what", "where", "when", "why", "who", "which", "can", "could", "would", "is", "are", "do", "does"]
    has_question_mark = "?" in message

    # Help indicators
    help_words = ["help", "stuck", "issue", "problem", "error", "bug", "broken", "doesn't work", "not working", "failed", "fix"]

    # Greeting indicators
    greeting_words = ["hi", "hello", "hey", "yo", "sup", "what's up", "wassup", "hola", "greetings"]

    # Feedback indicators
    feedback_words = ["suggestion", "idea", "feedback", "feature", "request", "should", "could you add"]

    # Spam/low effort indicators
    if len(message.strip()) < 3 or message.strip() in [".", "?", "!", "??", "!!!"]:
        log.tree("Ping Intent Classified", [
            ("Intent", "Low-effort/Spam"),
            ("Message", message[:30] + "..." if len(message) > 30 else message),
            ("Response", "Dismissive"),
        ], emoji="🚫")
        return "INTENT: This looks like a low-effort ping. Be dismissive."

    # Check for greetings (usually at start)
    first_word = msg_lower.split()[0] if msg_lower.split() else ""
    if first_word in greeting_words or msg_lower.startswith(tuple(greeting_words)):
        log.tree("Ping Intent Classified", [
            ("Intent", "Greeting"),
            ("Trigger", first_word),
            ("Response", "Casual/brief"),
        ], emoji="👋")
        return "INTENT: User is just saying hi/greeting you. Keep it casual and brief."

    # Check for help/issues
    if any(word in msg_lower for word in help_words):
        matched = [w for w in help_words if w in msg_lower][0]
        log.tree("Ping Intent Classified", [
            ("Intent", "Help Request"),
            ("Trigger", matched),
            ("Response", "Helpful"),
        ], emoji="🆘")
        return "INTENT: User needs help with something. Be helpful but maintain your personality."

    # Check for questions
    if has_question_mark or any(msg_lower.startswith(w) for w in question_words):
        log.tree("Ping Intent Classified", [
            ("Intent", "Question"),
            ("Has ?", str(has_question_mark)),
            ("Response", "Direct answer"),
        ], emoji="❓")
        return "INTENT: User is asking a question. Answer it directly."

    # Check for feedback
    if any(word in msg_lower for word in feedback_words):
        matched = [w for w in feedback_words if w in msg_lower][0]
        log.tree("Ping Intent Classified", [
            ("Intent", "Feedback"),
            ("Trigger", matched),
            ("Response", "Acknowledge"),
        ], emoji="💡")
        return "INTENT: User is giving feedback or making a suggestion. Acknowledge it."

    log.tree("Ping Intent Classified", [
        ("Intent", "Unclear"),
        ("Response", "AI decides"),
    ], emoji="🤔")
    return ""  # Unclear intent, let AI figure it out


# =============================================================================
# Language Detection
# =============================================================================

# Arabic Unicode ranges
ARABIC_RANGE = range(0x0600, 0x06FF)  # Arabic
ARABIC_EXTENDED = range(0x0750, 0x077F)  # Arabic Supplement
ARABIC_PRESENTATION_A = range(0xFB50, 0xFDFF)  # Arabic Presentation Forms-A
ARABIC_PRESENTATION_B = range(0xFE70, 0xFEFF)  # Arabic Presentation Forms-B


def _detect_language(text: str) -> str:
    """
    Detect if text is primarily Arabic or English.

    Returns: 'arabic', 'english', or 'mixed'
    """
    if not text:
        return "english"

    arabic_chars = 0
    english_chars = 0

    for char in text:
        code = ord(char)
        if (code in ARABIC_RANGE or code in ARABIC_EXTENDED or
            code in ARABIC_PRESENTATION_A or code in ARABIC_PRESENTATION_B):
            arabic_chars += 1
        elif char.isalpha() and ord(char) < 128:
            english_chars += 1

    total = arabic_chars + english_chars
    if total == 0:
        return "english"

    arabic_ratio = arabic_chars / total

    if arabic_ratio > 0.5:
        return "arabic"
    elif arabic_ratio > 0.2:
        return "mixed"
    else:
        return "english"


def _verify_language_match(input_text: str, response_text: str) -> tuple[bool, str, str]:
    """
    Verify that the AI response matches the input language.

    Returns: (matches, input_lang, response_lang)
    """
    input_lang = _detect_language(input_text)
    response_lang = _detect_language(response_text)

    # Mixed is acceptable for either
    if input_lang == "mixed" or response_lang == "mixed":
        return True, input_lang, response_lang

    matches = input_lang == response_lang
    return matches, input_lang, response_lang


# =============================================================================
# Parallel Context Fetching
# =============================================================================

async def _fetch_all_context(
    user_id: int,
    message: str,
) -> dict:
    """
    Fetch all context in parallel for better performance.

    Returns dict with: dev_activity, rag_context, user_context, sentiment_context
    """
    async def get_lanyard():
        return await _get_developer_activity_context()

    async def get_rag():
        if rag_service.is_available:
            return rag_service.build_context(message, max_tokens=1500)
        return ""

    async def get_user_memory():
        # Record interaction (also extracts topics)
        user_memory.record_interaction(user_id, message)
        # Get user context (topics + patterns)
        return user_memory.get_user_context(user_id)

    async def get_sentiment():
        return user_memory.detect_current_sentiment(message)

    # Fetch all in parallel
    start = time.time()
    results = await asyncio.gather(
        get_lanyard(),
        get_rag(),
        get_user_memory(),
        get_sentiment(),
        return_exceptions=True,
    )

    elapsed = time.time() - start

    # Handle results (replace exceptions with empty strings)
    dev_activity = results[0] if not isinstance(results[0], Exception) else ""
    rag_context = results[1] if not isinstance(results[1], Exception) else ""
    user_context = results[2] if not isinstance(results[2], Exception) else ""
    sentiment_context = results[3] if not isinstance(results[3], Exception) else ""

    log.tree("Parallel Context Fetch", [
        ("Time", f"{elapsed*1000:.0f}ms"),
        ("Lanyard", "Yes" if dev_activity else "No"),
        ("RAG", "Yes" if rag_context else "No"),
        ("User Memory", "Yes" if user_context else "No"),
        ("Sentiment", "Yes" if sentiment_context else "No"),
    ], emoji="⚡")

    return {
        "dev_activity": dev_activity,
        "rag_context": rag_context,
        "user_context": user_context,
        "sentiment_context": sentiment_context,
    }


def _get_repeated_question_context(user_id: int, message: str) -> str:
    """
    Check if user has asked similar questions recently.

    Uses RAG to find semantically similar past questions from this user.
    """
    if not rag_service.is_available:
        return ""

    try:
        # Search for similar messages
        results = rag_service.retrieve(
            message,
            n_results=10,
            collections=[rag_service.MESSAGES_COLLECTION]
        )

        # Filter to this user's messages
        user_messages = [
            r for r in results
            if r.metadata.get("author_id") == str(user_id) and r.relevance > 0.7
        ]

        if len(user_messages) >= 2:
            top_match = user_messages[0]
            log.tree("Repeated Question Detected", [
                ("User ID", str(user_id)),
                ("Similar Questions", str(len(user_messages))),
                ("Top Match Score", f"{top_match.relevance:.2f}"),
                ("Previous", top_match.content[:40] + "..."),
                ("Annoyance", "High"),
            ], emoji="🔄")
            return f"REPEATED QUESTION: This user has asked {len(user_messages)} similar questions before. Be a bit more annoyed - they should know this by now."
        elif len(user_messages) == 1:
            match = user_messages[0]
            log.tree("Repeated Question Detected", [
                ("User ID", str(user_id)),
                ("Similar Questions", "1"),
                ("Match Score", f"{match.relevance:.2f}"),
                ("Previous", match.content[:40] + "..."),
                ("Annoyance", "Low"),
            ], emoji="🔁")
            return "REPEATED QUESTION: This user asked something similar before. You can reference that if relevant."

        return ""

    except Exception as e:
        log.tree("Repeated Question Check Failed", [
            ("Error", str(e)[:50]),
        ], emoji="⚠️")
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

    # Check if user has used their follow-up already
    followup_count = conv.get("followup_count", 0)
    if followup_count >= MAX_FOLLOWUPS:
        # Already used follow-up, check full cooldown
        now = time.time()
        last_response = _ai_cooldowns.get(user_id, 0)
        time_since_last = now - last_response

        if time_since_last < AI_COOLDOWN_SECONDS:
            remaining = int(AI_COOLDOWN_SECONDS - time_since_last)
            remaining_mins = remaining // 60
            remaining_secs = remaining % 60

            log.tree("Follow-up Limit Reached", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("User ID", str(user_id)),
                ("Followups Used", str(followup_count)),
                ("Cooldown Remaining", f"{remaining_mins}m {remaining_secs}s"),
            ], emoji="🚫")
            try:
                if remaining_mins > 0:
                    await message.reply(f"You've used your follow-up. Wait {remaining_mins}m {remaining_secs}s to ping me again.", delete_after=10)
                else:
                    await message.reply(f"You've used your follow-up. Wait {remaining_secs}s to ping me again.", delete_after=10)
            except Exception:
                pass
            return

    # Check follow-up cooldown (shorter than initial, just to prevent spam)
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

    # Fetch all context in parallel (Lanyard, RAG, User Memory, Sentiment)
    context = await _fetch_all_context(user_id, content)
    dev_activities = context["dev_activity"]
    rag_context = context["rag_context"]
    user_context = context["user_context"]
    sentiment_context = context["sentiment_context"]

    # Fallback to basic server context if RAG not available
    if not rag_context:
        rag_context = server_intel.get_server_context()

    # Combine all context
    combined_context = rag_context
    if user_context:
        combined_context = f"{combined_context}\n\n{user_context}" if combined_context else user_context
    if sentiment_context:
        combined_context = f"{combined_context}\n\n{sentiment_context}" if combined_context else sentiment_context

    # Detect input language for verification
    input_language = _detect_language(content)

    # Generate AI response with conversation history
    try:
        async with message.channel.typing():
            response = await ai_service.chat(
                message=content,
                user_name=user_name,
                dev_activity=dev_activities,
                conversation_history=conv["messages"],
                server_context=combined_context,
            )

        if response:
            # Verify language match
            lang_matches, input_lang, response_lang = _verify_language_match(content, response)
            if not lang_matches:
                log.tree("Language Mismatch (Reply)", [
                    ("Input", input_lang),
                    ("Response", response_lang),
                    ("Action", "Regenerating"),
                ], emoji="🌐")

                # Regenerate with explicit language instruction
                lang_instruction = f"CRITICAL: The user wrote in {input_lang.upper()}. You MUST respond ENTIRELY in {input_lang.upper()}."

                response = await ai_service.chat(
                    message=content,
                    user_name=user_name,
                    dev_activity=dev_activities,
                    conversation_history=conv["messages"],
                    server_context=f"{combined_context}\n\n{lang_instruction}",
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

            # Increment follow-up count
            conv["followup_count"] = conv.get("followup_count", 0) + 1
            followups_used = conv["followup_count"]

            # Add to conversation history
            _add_to_conversation(user_id, "user", content)
            _add_to_conversation(user_id, "assistant", response, sent_message.id)

            log.tree("Conversation Reply Sent", [
                ("User", f"{message.author.name} ({message.author.display_name})"),
                ("User ID", str(user_id)),
                ("Response Length", str(len(response))),
                ("Followups Used", f"{followups_used}/{MAX_FOLLOWUPS}"),
                ("Total Turns", str(len(conv["messages"]) + 2)),
            ], emoji="✅")

            # If max followups reached, clear conversation to prevent further replies
            if followups_used >= MAX_FOLLOWUPS:
                _clear_conversation(user_id)
                log.tree("Conversation Ended", [
                    ("User", f"{message.author.name} ({message.author.display_name})"),
                    ("User ID", str(user_id)),
                    ("Reason", "Max follow-ups reached"),
                    ("Next Ping Available", f"{AI_COOLDOWN_SECONDS // 60}m"),
                ], emoji="🔒")
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
    # Run periodic memory cleanup
    _cleanup_memory()

    if message.author.bot:
        return

    # Increment weekly message counter (only for guild messages)
    if message.guild and message.guild.id == config.GUILD_ID:
        await message_counter.increment()

        # Record message for server intelligence
        server_intel.record_message(message)

        # Auto-learn from message (indexes + extracts FAQs from Q&A patterns)
        await auto_learner.learn_from_message(message)

        # Check for owner correction (owner sends message after bot responded)
        if message.author.id == config.OWNER_ID:
            channel_id = message.channel.id
            correction = feedback_learner.check_for_correction(
                channel_id=channel_id,
                owner_message=message.content,
            )
            if correction:
                log.tree("Owner Correction Learned", [
                    ("Channel", message.channel.name if hasattr(message.channel, 'name') else str(channel_id)),
                    ("Correction", message.content[:50] + "..." if len(message.content) > 50 else message.content),
                ], emoji="📝")

    # Check for reply to AI response (multi-turn conversation)
    if message.reference and message.reference.message_id:
        await _handle_conversation_reply(bot, message)


# =============================================================================
# AutoMod Action Handler
# =============================================================================

async def on_automod_action(bot: discord.Client, execution: discord.AutoModAction) -> None:
    """
    Handle AutoMod actions - respond with AI when developer ping is blocked.

    DISABLED: Auto-response feature is currently disabled.
    """
    # Feature disabled - do not auto-respond to pings
    return

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

    # Fetch all context in parallel (Lanyard, RAG, User Memory, Sentiment)
    context = await _fetch_all_context(user_id, cleaned_content)
    dev_activities = context["dev_activity"]
    rag_context = context["rag_context"]
    user_context = context["user_context"]
    sentiment_context = context["sentiment_context"]

    # Get ping history context
    ping_context = _get_ping_context(user_id, cleaned_content)

    # Get time-aware context
    time_context = _get_time_context()

    # Classify ping intent
    intent_context = await _classify_ping_intent(cleaned_content)

    # Check for repeated questions from this user
    repeated_context = _get_repeated_question_context(user_id, cleaned_content)

    # Fallback to basic server context if RAG not available
    server_context = ""
    if not rag_context:
        server_context = server_intel.get_server_context()

    # Detect input language for verification later
    input_language = _detect_language(cleaned_content)

    log.tree("Generating AI Response", [
        ("Original Message", content[:80] + "..." if len(content) > 80 else content),
        ("Dev Activity", dev_activities if dev_activities else "None"),
        ("Ping Context", ping_context if ping_context else "First ping"),
        ("Time Context", time_context[:30] + "..." if time_context else "Normal hours"),
        ("Intent", intent_context[:30] + "..." if intent_context else "Unclear"),
        ("Repeated", repeated_context[:30] + "..." if repeated_context else "No"),
        ("RAG Context", "Yes" if rag_context else "No"),
        ("User Memory", "Yes" if user_context else "No"),
        ("Sentiment", sentiment_context[:30] + "..." if sentiment_context else "Neutral"),
        ("Input Language", input_language),
    ], emoji="🤖")

    # Get existing conversation history (for multi-turn)
    conv = _get_conversation(user_id)
    conversation_history = conv["messages"] if conv else None

    # Combine all context into server_context
    combined_context = rag_context or server_context
    if user_context:
        combined_context = f"{combined_context}\n\n{user_context}" if combined_context else user_context
    if sentiment_context:
        combined_context = f"{combined_context}\n\n{sentiment_context}" if combined_context else sentiment_context

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
                server_context=combined_context,
                time_context=time_context,
                intent_context=intent_context,
                repeated_context=repeated_context,
            )

        if response:
            # Verify language match
            lang_matches, input_lang, response_lang = _verify_language_match(cleaned_content, response)
            if not lang_matches:
                log.tree("Language Mismatch Detected", [
                    ("Input", input_lang),
                    ("Response", response_lang),
                    ("Action", "Regenerating"),
                ], emoji="🌐")

                # Add explicit language instruction and regenerate
                lang_instruction = f"CRITICAL: The user wrote in {input_lang.upper()}. You MUST respond ENTIRELY in {input_lang.upper()}. Do not mix languages."

                response = await ai_service.chat(
                    message=cleaned_content,
                    user_name=user_name,
                    original_blocked=content,
                    dev_activity=dev_activities,
                    ping_context=ping_context,
                    conversation_history=conversation_history,
                    server_context=f"{combined_context}\n\n{lang_instruction}",
                    time_context=time_context,
                    intent_context=intent_context,
                    repeated_context=repeated_context,
                )

                # Log regeneration result
                if response:
                    _, _, new_response_lang = _verify_language_match(cleaned_content, response)
                    log.tree("Language Regeneration Complete", [
                        ("New Response Lang", new_response_lang),
                    ], emoji="✅")

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

            # Track bot response for feedback learning (corrections + reactions)
            feedback_learner.track_bot_response(
                message_id=sent_message.id,
                channel_id=execution.channel_id,
                response=response,
                original_question=cleaned_content,
            )

            log.tree("AI Response Sent", [
                ("To User", user_name),
                ("Response Length", len(response)),
                ("Channel", f"#{channel.name}" if hasattr(channel, 'name') else str(channel)),
                ("Tracked", "Yes"),
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
