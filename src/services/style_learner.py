"""
TrippixnBot - Style Learner Service
===================================

Learns the owner's communication style from their messages
and builds a style profile for AI responses.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional
from openai import OpenAI, RateLimitError

from src.core import config, log


# =============================================================================
# Style Learner Service
# =============================================================================

class StyleLearner:
    """
    Learns the owner's communication style from their messages.

    This service:
    - Collects owner messages over time
    - Analyzes them for style patterns using AI
    - Builds a style profile (phrases, tone, emoji usage, etc.)
    - Provides the style context for AI responses
    """

    # How many messages to keep for analysis
    MAX_MESSAGES = 200

    # Minimum messages before generating style profile
    MIN_MESSAGES_FOR_ANALYSIS = 30

    # How often to re-analyze style (in seconds)
    ANALYSIS_INTERVAL = 3600  # 1 hour

    # Data file paths
    DATA_DIR = Path(__file__).parent.parent.parent / "data"
    MESSAGES_FILE = DATA_DIR / "owner_messages.json"
    STYLE_FILE = DATA_DIR / "owner_style.json"

    def __init__(self):
        self.openai_client: Optional[OpenAI] = None
        self._messages: deque = deque(maxlen=self.MAX_MESSAGES)
        self._style_profile: dict = {}
        self._last_analysis: float = 0
        self._initialized = False
        self._analysis_task: Optional[asyncio.Task] = None
        self._running = False

    async def setup(self) -> bool:
        """Initialize the style learner."""
        if not config.OPENAI_API_KEY:
            log.tree("Style Learner Disabled", [
                ("Reason", "No OpenAI API key"),
            ], emoji="⚠️")
            return False

        if not config.OWNER_ID:
            log.tree("Style Learner Disabled", [
                ("Reason", "No owner ID configured"),
            ], emoji="⚠️")
            return False

        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

        # Ensure data directory exists
        self.DATA_DIR.mkdir(exist_ok=True)

        # Load existing data
        self._load_messages()
        self._load_style()

        self._initialized = True
        self._running = True

        # Start background analysis task
        self._analysis_task = asyncio.create_task(self._analysis_loop())

        log.tree("Style Learner Initialized", [
            ("Owner ID", str(config.OWNER_ID)),
            ("Messages Stored", str(len(self._messages))),
            ("Has Style Profile", "Yes" if self._style_profile else "No"),
        ], emoji="🎨")

        return True

    def stop(self) -> None:
        """Stop the style learner."""
        self._running = False
        if self._analysis_task:
            self._analysis_task.cancel()
            self._analysis_task = None

        # Save current state
        self._save_messages()

        log.tree("Style Learner Stopped", [
            ("Messages Saved", str(len(self._messages))),
        ], emoji="🛑")

    def _load_messages(self) -> None:
        """Load stored messages from disk."""
        if self.MESSAGES_FILE.exists():
            try:
                with open(self.MESSAGES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._messages = deque(data.get("messages", []), maxlen=self.MAX_MESSAGES)

                log.tree("Owner Messages Loaded", [
                    ("Count", str(len(self._messages))),
                    ("File", str(self.MESSAGES_FILE.name)),
                ], emoji="📂")
            except Exception as e:
                log.tree("Owner Messages Load Failed", [
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")
        else:
            log.tree("Owner Messages File", [
                ("Status", "No existing file, starting fresh"),
            ], emoji="📄")

    def _save_messages(self) -> None:
        """Save messages to disk."""
        try:
            with open(self.MESSAGES_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "messages": list(self._messages),
                    "updated_at": datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)

            log.tree("Owner Messages Saved", [
                ("Count", str(len(self._messages))),
            ], emoji="💾")
        except Exception as e:
            log.tree("Owner Messages Save Failed", [
                ("Error", str(e)[:50]),
            ], emoji="⚠️")

    def _load_style(self) -> None:
        """Load style profile from disk."""
        if self.STYLE_FILE.exists():
            try:
                with open(self.STYLE_FILE, "r", encoding="utf-8") as f:
                    self._style_profile = json.load(f)

                log.tree("Style Profile Loaded", [
                    ("Phrases", str(len(self._style_profile.get("phrases", [])))),
                    ("Quirks", str(len(self._style_profile.get("quirks", [])))),
                    ("Last Updated", self._style_profile.get("updated_at", "Unknown")[:10]),
                ], emoji="📂")
            except Exception as e:
                log.tree("Style Profile Load Failed", [
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")
        else:
            log.tree("Style Profile File", [
                ("Status", "No existing profile, will analyze when ready"),
            ], emoji="📄")

    def _save_style(self) -> None:
        """Save style profile to disk."""
        try:
            self._style_profile["updated_at"] = datetime.now().isoformat()
            with open(self.STYLE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._style_profile, f, ensure_ascii=False, indent=2)

            log.tree("Style Profile Saved", [
                ("Phrases", str(len(self._style_profile.get("phrases", [])))),
            ], emoji="💾")
        except Exception as e:
            log.tree("Style Profile Save Failed", [
                ("Error", str(e)[:50]),
            ], emoji="⚠️")

    def add_message(self, content: str, channel_name: str = "unknown") -> None:
        """
        Add an owner message for style learning.

        Args:
            content: The message content
            channel_name: Channel where it was sent
        """
        if not self._initialized:
            return

        # Skip very short messages
        if len(content) < 5:
            return

        # Skip commands
        if content.startswith(("/", "!", ".")):
            return

        was_empty = len(self._messages) == 0

        self._messages.append({
            "content": content,
            "channel": channel_name,
            "timestamp": datetime.now().isoformat(),
        })

        # Log first message
        if was_empty:
            log.tree("Owner Style Learning Started", [
                ("First Message", f"#{channel_name}"),
                ("Content Preview", content[:50] + "..." if len(content) > 50 else content),
            ], emoji="🎯")

        # Log every 20 messages
        elif len(self._messages) % 20 == 0:
            log.tree("Owner Messages Updated", [
                ("Total", str(len(self._messages))),
                ("Latest Channel", f"#{channel_name}"),
                ("Until Analysis", f"{self.MIN_MESSAGES_FOR_ANALYSIS - len(self._messages)} more" if len(self._messages) < self.MIN_MESSAGES_FOR_ANALYSIS else "Ready"),
            ], emoji="📝")

        # Save every 10 messages
        if len(self._messages) % 10 == 0:
            self._save_messages()

    async def _analysis_loop(self) -> None:
        """Background loop to periodically analyze style."""
        log.tree("Style Analysis Loop Started", [
            ("Interval", f"{self.ANALYSIS_INTERVAL // 60} minutes"),
        ], emoji="🔄")

        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute

                if not self._running:
                    break

                now = time.time()
                messages_count = len(self._messages)

                # Check if we should analyze
                should_analyze = (
                    messages_count >= self.MIN_MESSAGES_FOR_ANALYSIS and
                    (now - self._last_analysis > self.ANALYSIS_INTERVAL or not self._style_profile)
                )

                if should_analyze:
                    log.tree("Style Analysis Triggered", [
                        ("Messages", str(messages_count)),
                        ("Has Profile", "Yes" if self._style_profile else "No"),
                    ], emoji="🔬")
                    await self._analyze_style()
                    self._last_analysis = now

            except asyncio.CancelledError:
                log.tree("Style Analysis Loop Cancelled", [], emoji="🛑")
                break
            except Exception as e:
                log.tree("Style Analysis Loop Error", [
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")
                await asyncio.sleep(60)

        log.tree("Style Analysis Loop Ended", [], emoji="🏁")

    async def _analyze_style(self) -> None:
        """Analyze collected messages and build style profile."""
        if not self.openai_client:
            log.tree("Style Analysis Skipped", [
                ("Reason", "No OpenAI client"),
            ], emoji="⚠️")
            return

        if len(self._messages) < self.MIN_MESSAGES_FOR_ANALYSIS:
            log.tree("Style Analysis Skipped", [
                ("Reason", f"Need {self.MIN_MESSAGES_FOR_ANALYSIS} messages"),
                ("Current", str(len(self._messages))),
            ], emoji="⚠️")
            return

        # Get recent messages for analysis
        messages_text = "\n".join([
            f"[#{m['channel']}] {m['content']}"
            for m in list(self._messages)[-100:]  # Last 100 messages
        ])

        log.tree("Analyzing Owner Style", [
            ("Messages", str(len(self._messages))),
        ], emoji="🎨")

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """Analyze these Discord messages from ONE person and extract their unique communication style.

Output a JSON object with these fields:
{
    "tone": "brief description of their overall tone (e.g., 'casual and blunt', 'sarcastic but helpful')",
    "sentence_style": "how they structure sentences (e.g., 'short fragments', 'uses incomplete sentences', 'direct and to the point')",
    "phrases": ["list of 5-10 common phrases or expressions they use"],
    "emoji_usage": "how they use emojis (e.g., 'rarely uses emojis', 'uses lol/lmao often', 'occasional emojis')",
    "vocabulary": "their vocabulary style (e.g., 'casual slang', 'mix of formal and informal', 'gaming terminology')",
    "quirks": ["list of 3-5 unique speaking patterns or quirks"],
    "response_length": "typical response length (e.g., 'very short 1-2 sentences', 'medium length', 'varies')",
    "capitalization": "how they handle caps (e.g., 'rarely capitalizes', 'normal capitalization', 'all lowercase')",
    "punctuation": "punctuation habits (e.g., 'minimal punctuation', 'uses ... often', 'rarely uses periods')"
}

Be specific and extract ACTUAL patterns from their messages. Only include patterns you can clearly identify."""
                    },
                    {
                        "role": "user",
                        "content": f"Analyze these messages:\n\n{messages_text}"
                    }
                ],
                max_tokens=800,
                temperature=0.3,
            )

            result = response.choices[0].message.content

            # Parse JSON from response
            # Handle potential markdown code blocks
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]

            try:
                style_data = json.loads(result.strip())
                self._style_profile = style_data
                self._save_style()

                log.tree("Style Profile Updated", [
                    ("Tone", style_data.get("tone", "Unknown")[:40]),
                    ("Phrases", str(len(style_data.get("phrases", [])))),
                    ("Quirks", str(len(style_data.get("quirks", [])))),
                ], emoji="✅")

            except json.JSONDecodeError as e:
                log.tree("Style Parse Failed", [
                    ("Error", str(e)[:50]),
                    ("Response", result[:100]),
                ], emoji="⚠️")

        except RateLimitError:
            log.tree("Style Analysis Rate Limited", [], emoji="🚨")
        except Exception as e:
            log.tree("Style Analysis Failed", [
                ("Error", type(e).__name__),
                ("Message", str(e)[:50]),
            ], emoji="❌")

    def get_style_prompt(self) -> Optional[str]:
        """
        Get the style profile as a prompt addition.

        Returns:
            Style instructions for the AI, or None if no profile
        """
        if not self._style_profile:
            return None

        parts = ["OWNER'S COMMUNICATION STYLE (mimic this exactly):"]

        if tone := self._style_profile.get("tone"):
            parts.append(f"- Tone: {tone}")

        if sentence_style := self._style_profile.get("sentence_style"):
            parts.append(f"- Sentence style: {sentence_style}")

        if phrases := self._style_profile.get("phrases"):
            parts.append(f"- Common phrases to use: {', '.join(phrases[:7])}")

        if emoji_usage := self._style_profile.get("emoji_usage"):
            parts.append(f"- Emoji usage: {emoji_usage}")

        if vocabulary := self._style_profile.get("vocabulary"):
            parts.append(f"- Vocabulary: {vocabulary}")

        if quirks := self._style_profile.get("quirks"):
            parts.append(f"- Speaking quirks: {', '.join(quirks[:5])}")

        if response_length := self._style_profile.get("response_length"):
            parts.append(f"- Response length: {response_length}")

        if capitalization := self._style_profile.get("capitalization"):
            parts.append(f"- Capitalization: {capitalization}")

        if punctuation := self._style_profile.get("punctuation"):
            parts.append(f"- Punctuation: {punctuation}")

        parts.append("\nIMPORTANT: Sound EXACTLY like the owner based on these patterns. Use their phrases, match their tone, and copy their texting style.")

        return "\n".join(parts)

    def get_stats(self) -> dict:
        """Get style learner statistics."""
        return {
            "initialized": self._initialized,
            "messages_count": len(self._messages),
            "has_style_profile": bool(self._style_profile),
            "style_updated": self._style_profile.get("updated_at") if self._style_profile else None,
            "phrases_count": len(self._style_profile.get("phrases", [])) if self._style_profile else 0,
        }

    async def force_analyze(self) -> bool:
        """Force an immediate style analysis."""
        if len(self._messages) < self.MIN_MESSAGES_FOR_ANALYSIS:
            log.tree("Force Analysis Skipped", [
                ("Reason", f"Need {self.MIN_MESSAGES_FOR_ANALYSIS} messages, have {len(self._messages)}"),
            ], emoji="⚠️")
            return False

        await self._analyze_style()
        return bool(self._style_profile)


# Global instance
style_learner = StyleLearner()
