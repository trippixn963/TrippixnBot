"""
TrippixnBot - Auto Learning Service
===================================

Automatically learns from server messages and builds knowledge.
Runs continuously to keep the RAG database up to date.

Author: حَـــــنَّـــــا
"""

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional
import discord
from openai import OpenAI, RateLimitError

from src.core import config, log
from src.services.rag_service import rag_service
from src.services.style_learner import style_learner


# =============================================================================
# Auto Learning Service
# =============================================================================

class AutoLearner:
    """
    Automatically learns from server messages and extracts knowledge.

    This service:
    - Scrapes message history from all channels on startup
    - Extracts FAQs, rules, and important info using AI
    - Continuously learns from new messages
    - Auto-generates channel summaries
    """

    # How many messages to fetch per channel on startup
    HISTORY_LIMIT = 500

    # Minimum messages needed to analyze a channel
    MIN_MESSAGES_FOR_ANALYSIS = 50

    # How often to run deep analysis (in seconds)
    ANALYSIS_INTERVAL = 3600  # 1 hour

    # Batch size for AI analysis
    ANALYSIS_BATCH_SIZE = 50

    # Rate limiting settings
    MAX_API_CALLS_PER_MINUTE = 50  # OpenAI limit is 60 RPM for most tiers
    RATE_LIMIT_WINDOW = 60  # seconds
    RATE_LIMIT_BACKOFF_BASE = 5  # seconds - base backoff time
    RATE_LIMIT_BACKOFF_MAX = 300  # seconds - max backoff (5 minutes)

    def __init__(self):
        self.bot: Optional[discord.Client] = None
        self.guild: Optional[discord.Guild] = None
        self.openai_client: Optional[OpenAI] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_analysis: float = 0
        self._initialized = False

        # Track what we've learned
        self._channels_analyzed: set[int] = set()
        self._messages_processed: int = 0

        # Rate limiting
        self._api_call_timestamps: deque = deque()  # Track timestamps of API calls
        self._consecutive_rate_limits: int = 0  # Track consecutive rate limit hits
        self._rate_limit_until: float = 0  # Timestamp until which we should wait

    async def setup(self, bot: discord.Client, guild_id: int) -> bool:
        """Initialize the auto learner."""
        if not config.OPENAI_API_KEY:
            log.tree("Auto Learner Disabled", [
                ("Reason", "No OpenAI API key"),
            ], emoji="⚠️")
            return False

        self.bot = bot
        self.guild = bot.get_guild(guild_id)
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

        if not self.guild:
            log.tree("Auto Learner Failed", [
                ("Reason", "Guild not found"),
                ("Guild ID", str(guild_id)),
            ], emoji="❌")
            return False

        self._initialized = True

        log.tree("Auto Learner Initialized", [
            ("Guild", self.guild.name),
            ("Channels", str(len(self.guild.text_channels))),
            ("Rate Limit", f"{self.MAX_API_CALLS_PER_MINUTE}/min"),
        ], emoji="🎓")

        return True

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    async def _wait_for_rate_limit(self) -> None:
        """Wait if we're approaching or hitting rate limits."""
        now = time.time()

        # Check if we're in a forced backoff period
        if now < self._rate_limit_until:
            wait_time = self._rate_limit_until - now
            log.tree("Rate Limit Backoff", [
                ("Waiting", f"{wait_time:.1f}s"),
                ("Reason", "Previous rate limit hit"),
            ], emoji="⏳")
            await asyncio.sleep(wait_time)
            return

        # Clean old timestamps outside the window
        cutoff = now - self.RATE_LIMIT_WINDOW
        while self._api_call_timestamps and self._api_call_timestamps[0] < cutoff:
            self._api_call_timestamps.popleft()

        # Check if we're approaching the limit
        calls_in_window = len(self._api_call_timestamps)

        if calls_in_window >= self.MAX_API_CALLS_PER_MINUTE:
            # Calculate how long to wait for oldest call to expire
            oldest_call = self._api_call_timestamps[0]
            wait_time = (oldest_call + self.RATE_LIMIT_WINDOW) - now + 1  # +1 buffer

            log.tree("Rate Limit Prevention", [
                ("Calls in Window", str(calls_in_window)),
                ("Max Allowed", str(self.MAX_API_CALLS_PER_MINUTE)),
                ("Waiting", f"{wait_time:.1f}s"),
            ], emoji="🛑")

            await asyncio.sleep(wait_time)

        elif calls_in_window >= self.MAX_API_CALLS_PER_MINUTE * 0.8:
            # At 80% capacity, add a small delay to spread calls
            delay = 1.0
            log.tree("Rate Limit Throttle", [
                ("Calls in Window", str(calls_in_window)),
                ("Capacity", f"{int(calls_in_window / self.MAX_API_CALLS_PER_MINUTE * 100)}%"),
                ("Adding Delay", f"{delay}s"),
            ], emoji="🐢")
            await asyncio.sleep(delay)

    def _record_api_call(self) -> None:
        """Record that an API call was made."""
        self._api_call_timestamps.append(time.time())
        # Reset consecutive rate limits on successful call
        self._consecutive_rate_limits = 0

    def _handle_rate_limit_error(self) -> float:
        """Handle a rate limit error with exponential backoff."""
        self._consecutive_rate_limits += 1

        # Exponential backoff: 5s, 10s, 20s, 40s, ... up to max
        backoff = min(
            self.RATE_LIMIT_BACKOFF_BASE * (2 ** (self._consecutive_rate_limits - 1)),
            self.RATE_LIMIT_BACKOFF_MAX
        )

        self._rate_limit_until = time.time() + backoff

        log.tree("Rate Limit Hit", [
            ("Consecutive Hits", str(self._consecutive_rate_limits)),
            ("Backoff", f"{backoff}s"),
            ("Strategy", "Exponential backoff"),
        ], emoji="🚨")

        return backoff

    def _get_rate_limit_stats(self) -> dict:
        """Get current rate limiting statistics."""
        now = time.time()

        # Clean old timestamps
        cutoff = now - self.RATE_LIMIT_WINDOW
        while self._api_call_timestamps and self._api_call_timestamps[0] < cutoff:
            self._api_call_timestamps.popleft()

        return {
            "calls_in_window": len(self._api_call_timestamps),
            "max_calls": self.MAX_API_CALLS_PER_MINUTE,
            "capacity_pct": int(len(self._api_call_timestamps) / self.MAX_API_CALLS_PER_MINUTE * 100),
            "in_backoff": now < self._rate_limit_until,
            "backoff_remaining": max(0, self._rate_limit_until - now),
        }

    async def start(self) -> None:
        """Start the auto learning process."""
        if not self._initialized or self._running:
            return

        self._running = True

        log.tree("Auto Learner Starting", [
            ("Status", "Scraping history..."),
            ("Channels", str(len(self.guild.text_channels))),
        ], emoji="🚀")

        # Initial scrape of all channels
        await self._scrape_all_channels()

        # Start continuous learning loop
        self._task = asyncio.create_task(self._learning_loop())

        log.tree("Auto Learner Running", [
            ("Messages Indexed", str(self._messages_processed)),
            ("Channels Analyzed", str(len(self._channels_analyzed))),
        ], emoji="✅")

    def stop(self) -> None:
        """Stop the auto learner."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

        log.tree("Auto Learner Stopped", [
            ("Messages Processed", str(self._messages_processed)),
        ], emoji="🛑")

    async def _scrape_all_channels(self) -> None:
        """Scrape message history from all text channels."""
        if not self.guild:
            return

        for channel in self.guild.text_channels:
            try:
                await self._scrape_channel(channel)
                # Small delay to avoid rate limits
                await asyncio.sleep(1)
            except discord.Forbidden:
                log.tree("Channel Access Denied", [
                    ("Channel", f"#{channel.name}"),
                ], emoji="🔒")
            except Exception as e:
                log.tree("Channel Scrape Failed", [
                    ("Channel", f"#{channel.name}"),
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")

    async def _scrape_channel(self, channel: discord.TextChannel) -> None:
        """Scrape messages from a single channel."""
        messages = []
        message_count = 0

        try:
            async for message in channel.history(limit=self.HISTORY_LIMIT):
                if message.author.bot:
                    continue
                if not message.content or len(message.content) < 10:
                    continue

                messages.append({
                    "id": message.id,
                    "content": message.content,
                    "author": message.author.display_name,
                    "author_id": message.author.id,
                    "timestamp": message.created_at.timestamp(),
                })

                # Index in RAG
                if len(message.content) >= 20:
                    rag_service.index_message(
                        message_id=message.id,
                        content=message.content,
                        author_name=message.author.display_name,
                        author_id=message.author.id,
                        channel_name=channel.name,
                        channel_id=channel.id,
                    )
                    message_count += 1

        except Exception as e:
            log.tree("Message Fetch Failed", [
                ("Channel", f"#{channel.name}"),
                ("Error", str(e)[:50]),
            ], emoji="⚠️")
            return

        self._messages_processed += message_count

        # If enough messages, analyze the channel
        if len(messages) >= self.MIN_MESSAGES_FOR_ANALYSIS:
            await self._analyze_channel(channel, messages)
            self._channels_analyzed.add(channel.id)

        log.tree("Channel Scraped", [
            ("Channel", f"#{channel.name}"),
            ("Messages", str(message_count)),
            ("Analyzed", "Yes" if channel.id in self._channels_analyzed else "No"),
        ], emoji="📥")

    async def _analyze_channel(self, channel: discord.TextChannel, messages: list[dict]) -> None:
        """Use AI to analyze channel messages and extract knowledge."""
        if not self.openai_client:
            log.tree("Channel Analysis Skipped", [
                ("Channel", f"#{channel.name}"),
                ("Reason", "No OpenAI client"),
            ], emoji="⚠️")
            return

        # Take a sample of messages for analysis
        sample = messages[:self.ANALYSIS_BATCH_SIZE]
        messages_text = "\n".join([
            f"{m['author']}: {m['content'][:200]}"
            for m in sample
        ])

        # Wait for rate limit if needed
        await self._wait_for_rate_limit()

        log.tree("Analyzing Channel", [
            ("Channel", f"#{channel.name}"),
            ("Messages", str(len(sample))),
            ("Topic", channel.topic[:30] if channel.topic else "None"),
        ], emoji="🔬")

        try:
            # Ask AI to analyze the channel
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """Analyze these Discord messages and extract:
1. What this channel is used for (1-2 sentences)
2. Any FAQs you can identify (questions that get asked/answered)
3. Any rules or guidelines mentioned
4. Key topics discussed

Format your response as:
CHANNEL_PURPOSE: <description>
FAQ: <question> -> <answer>
FAQ: <question> -> <answer>
RULE: <rule>
TOPIC: <topic>

Only include what you can clearly identify from the messages. Be concise."""
                    },
                    {
                        "role": "user",
                        "content": f"Channel: #{channel.name}\nTopic: {channel.topic or 'None'}\n\nMessages:\n{messages_text}"
                    }
                ],
                max_tokens=500,
                temperature=0.3,
            )

            # Record successful API call
            self._record_api_call()

            analysis = response.choices[0].message.content

            log.tree("Channel Analysis Complete", [
                ("Channel", f"#{channel.name}"),
                ("Response Length", str(len(analysis))),
            ], emoji="✅")

            await self._process_analysis(channel, analysis)

        except RateLimitError as e:
            backoff = self._handle_rate_limit_error()
            log.tree("Channel Analysis Rate Limited", [
                ("Channel", f"#{channel.name}"),
                ("Backoff", f"{backoff}s"),
                ("Will Retry", "On next periodic analysis"),
            ], emoji="🚨")

        except Exception as e:
            log.tree("Channel Analysis Failed", [
                ("Channel", f"#{channel.name}"),
                ("Error", type(e).__name__),
                ("Message", str(e)[:50]),
            ], emoji="❌")

    async def _process_analysis(self, channel: discord.TextChannel, analysis: str) -> None:
        """Process AI analysis and add to RAG."""
        lines = analysis.strip().split("\n")

        # Track what we extracted
        extracted = {
            "purpose": False,
            "faqs": 0,
            "rules": 0,
            "topics": 0,
        }

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("CHANNEL_PURPOSE:"):
                purpose = line.replace("CHANNEL_PURPOSE:", "").strip()
                if purpose:
                    rag_service.add_channel_info(channel.name, purpose)
                    extracted["purpose"] = True
                    log.tree("Channel Purpose Learned", [
                        ("Channel", f"#{channel.name}"),
                        ("Purpose", purpose[:60] + "..." if len(purpose) > 60 else purpose),
                    ], emoji="📝")

            elif line.startswith("FAQ:"):
                faq = line.replace("FAQ:", "").strip()
                if "->" in faq:
                    parts = faq.split("->", 1)
                    if len(parts) == 2:
                        question = parts[0].strip()
                        answer = parts[1].strip()
                        if question and answer:
                            rag_service.add_faq(question, answer)
                            extracted["faqs"] += 1

            elif line.startswith("RULE:"):
                rule = line.replace("RULE:", "").strip()
                if rule:
                    rag_service.add_knowledge(rule, "rule")
                    extracted["rules"] += 1

            elif line.startswith("TOPIC:"):
                topic = line.replace("TOPIC:", "").strip()
                if topic:
                    rag_service.add_knowledge(
                        f"#{channel.name} discusses: {topic}",
                        "topic",
                        {"channel": channel.name}
                    )
                    extracted["topics"] += 1

        log.tree("Analysis Processed", [
            ("Channel", f"#{channel.name}"),
            ("Purpose", "Yes" if extracted["purpose"] else "No"),
            ("FAQs", str(extracted["faqs"])),
            ("Rules", str(extracted["rules"])),
            ("Topics", str(extracted["topics"])),
        ], emoji="🧠")

    async def _learning_loop(self) -> None:
        """Continuous learning loop."""
        log.tree("Learning Loop Started", [
            ("Interval", f"{self.ANALYSIS_INTERVAL // 60} minutes"),
        ], emoji="🔄")

        while self._running:
            try:
                await asyncio.sleep(self.ANALYSIS_INTERVAL)

                if not self._running:
                    break

                # Re-analyze channels periodically to catch new patterns
                now = time.time()
                if now - self._last_analysis > self.ANALYSIS_INTERVAL:
                    log.tree("Learning Loop Tick", [
                        ("Messages Processed", str(self._messages_processed)),
                        ("Channels Analyzed", str(len(self._channels_analyzed))),
                        ("Action", "Running periodic analysis"),
                    ], emoji="⏰")
                    await self._periodic_analysis()
                    self._last_analysis = now

            except asyncio.CancelledError:
                log.tree("Learning Loop Cancelled", [
                    ("Reason", "Task cancelled"),
                ], emoji="🛑")
                break
            except Exception as e:
                log.error_tree("Learning Loop Error", e, [
                    ("Status", "Will retry in 60s"),
                ])
                await asyncio.sleep(60)

        log.tree("Learning Loop Ended", [
            ("Total Messages", str(self._messages_processed)),
        ], emoji="🏁")

    async def _periodic_analysis(self) -> None:
        """Periodic deep analysis of active channels."""
        if not self.guild:
            return

        log.tree("Periodic Analysis Starting", [
            ("Channels", str(len(self.guild.text_channels))),
        ], emoji="🔄")

        # Find most active channels (by recent messages)
        active_channels = []

        for channel in self.guild.text_channels:
            try:
                # Check last message time
                if channel.last_message_id:
                    active_channels.append(channel)
            except Exception:
                continue

        # Analyze top 5 most recently active channels
        for channel in active_channels[:5]:
            try:
                messages = []
                # Get recent messages (last 24 hours)
                after = datetime.now(timezone.utc) - timedelta(hours=24)

                async for message in channel.history(limit=100, after=after):
                    if message.author.bot or not message.content:
                        continue
                    messages.append({
                        "content": message.content,
                        "author": message.author.display_name,
                    })

                if len(messages) >= 20:
                    await self._analyze_channel(channel, messages)

                await asyncio.sleep(2)

            except Exception as e:
                log.tree("Periodic Analysis Failed", [
                    ("Channel", f"#{channel.name}"),
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")

        log.tree("Periodic Analysis Complete", [
            ("Channels Analyzed", str(min(5, len(active_channels)))),
        ], emoji="✅")

    async def learn_from_message(self, message: discord.Message) -> None:
        """Learn from a single new message in real-time."""
        if not self._initialized:
            return

        if message.author.bot or not message.content:
            return

        # Track owner messages for style learning (even short ones)
        if message.author.id == config.OWNER_ID:
            channel_name = message.channel.name if hasattr(message.channel, 'name') else "DM"
            style_learner.add_message(message.content, channel_name)

        if not rag_service.is_available:
            return

        if len(message.content) < 20:
            return

        # Index the message
        channel_name = message.channel.name if hasattr(message.channel, 'name') else "DM"
        indexed = rag_service.index_message(
            message_id=message.id,
            content=message.content,
            author_name=message.author.display_name,
            author_id=message.author.id,
            channel_name=channel_name,
            channel_id=message.channel.id,
        )

        if indexed:
            self._messages_processed += 1
            # Log every 100 messages to avoid spam
            if self._messages_processed % 100 == 0:
                log.tree("Learning Progress", [
                    ("Messages Indexed", str(self._messages_processed)),
                    ("Latest Channel", f"#{channel_name}"),
                ], emoji="📊")

        # Check if this looks like a Q&A pattern
        # (someone asks a question, someone else answers)
        if "?" in message.content and message.reference:
            await self._check_qa_pattern(message)

    async def _check_qa_pattern(self, answer_message: discord.Message) -> None:
        """Check if a message is an answer to a question and extract FAQ."""
        if not self.openai_client:
            log.tree("Q&A Check Skipped", [
                ("Reason", "No OpenAI client"),
            ], emoji="⚠️")
            return

        try:
            # Get the question message
            ref = answer_message.reference
            if not ref or not ref.message_id:
                return

            channel = answer_message.channel
            question_message = await channel.fetch_message(ref.message_id)

            if not question_message or question_message.author.bot:
                return

            # Check if the referenced message is a question
            if "?" not in question_message.content:
                return

            log.tree("Q&A Pattern Detected", [
                ("Channel", f"#{channel.name}" if hasattr(channel, 'name') else "DM"),
                ("Question By", question_message.author.display_name),
                ("Answer By", answer_message.author.display_name),
            ], emoji="🔍")

            # Wait for rate limit if needed
            await self._wait_for_rate_limit()

            # Use AI to determine if this is a valid Q&A
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """Determine if this is a valid Q&A pair for a FAQ.
If yes, respond with: FAQ: <cleaned question> -> <cleaned answer>
If no (just conversation, not informative), respond with: NO

Keep answers concise and useful."""
                    },
                    {
                        "role": "user",
                        "content": f"Question: {question_message.content}\nAnswer: {answer_message.content}"
                    }
                ],
                max_tokens=150,
                temperature=0.3,
            )

            # Record successful API call
            self._record_api_call()

            result = response.choices[0].message.content.strip()

            if result.startswith("FAQ:"):
                faq = result.replace("FAQ:", "").strip()
                if "->" in faq:
                    parts = faq.split("->", 1)
                    if len(parts) == 2:
                        question = parts[0].strip()
                        answer = parts[1].strip()
                        if question and answer:
                            rag_service.add_faq(question, answer)
                            log.tree("FAQ Auto-Learned", [
                                ("Question", question[:50] + "..." if len(question) > 50 else question),
                                ("Answer", answer[:50] + "..." if len(answer) > 50 else answer),
                                ("Channel", f"#{channel.name}" if hasattr(channel, 'name') else "DM"),
                            ], emoji="💡")
            else:
                log.tree("Q&A Rejected", [
                    ("Reason", "Not informative FAQ"),
                    ("Question Preview", question_message.content[:30] + "..."),
                ], emoji="❌")

        except discord.NotFound:
            log.tree("Q&A Check Failed", [
                ("Reason", "Referenced message not found"),
            ], emoji="⚠️")
        except discord.Forbidden:
            log.tree("Q&A Check Failed", [
                ("Reason", "No permission to fetch message"),
            ], emoji="🔒")
        except RateLimitError:
            backoff = self._handle_rate_limit_error()
            log.tree("Q&A Check Rate Limited", [
                ("Backoff", f"{backoff}s"),
            ], emoji="🚨")
        except Exception as e:
            log.tree("Q&A Check Failed", [
                ("Error", type(e).__name__),
                ("Message", str(e)[:50]),
            ], emoji="❌")

    def get_stats(self) -> dict:
        """Get learning statistics."""
        return {
            "messages_processed": self._messages_processed,
            "channels_analyzed": len(self._channels_analyzed),
            "running": self._running,
            "initialized": self._initialized,
        }


# Global instance
auto_learner = AutoLearner()
