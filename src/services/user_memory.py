"""
TrippixnBot - User Memory Service
=================================

Tracks user topics, sentiment patterns, and preferences over time.

Author: حَـــــنَّـــــا
"""

import json
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional

from src.core import log


# =============================================================================
# User Memory Service
# =============================================================================

class UserMemory:
    """
    Tracks user interaction patterns and topics.

    Stores:
    - Topics they frequently ask about
    - Sentiment patterns (frequently frustrated?)
    - Interaction count

    Memory-optimized: limits max users and evicts least-recently-used.
    """

    DATA_FILE = Path(__file__).parent.parent.parent / "data" / "user_memory.json"
    MAX_USERS = 200  # Max users to keep in memory
    EVICT_COUNT = 20  # Number to evict when limit reached

    # Topic keywords to detect
    TOPIC_KEYWORDS = {
        "bot": ["bot", "command", "commands", "slash", "feature", "bug", "broken"],
        "server": ["server", "discord", "channel", "role", "rules", "invite"],
        "help": ["help", "how", "tutorial", "guide", "explain", "what is"],
        "music": ["music", "song", "spotify", "playlist", "listening"],
        "gaming": ["game", "gaming", "play", "playing", "steam", "xbox", "ps5"],
        "coding": ["code", "coding", "programming", "python", "javascript", "developer"],
        "personal": ["you", "your", "yourself", "owner", "admin", "busy"],
        "off-topic": ["random", "funny", "meme", "joke", "lol", "lmao"],
    }

    # Frustration indicators
    FRUSTRATION_WORDS = [
        "doesn't work", "not working", "broken", "stupid", "dumb", "useless",
        "annoying", "frustrated", "angry", "wtf", "why won't", "still not",
        "again", "help me", "please help", "i don't understand", "confused",
        "!!!",  "???"
    ]

    # Positive indicators
    POSITIVE_WORDS = [
        "thanks", "thank you", "awesome", "great", "cool", "nice", "love",
        "amazing", "perfect", "works", "working", "helped", "solved"
    ]

    def __init__(self):
        self._memory: dict[int, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load memory from file."""
        try:
            if self.DATA_FILE.exists():
                with open(self.DATA_FILE, "r") as f:
                    data = json.load(f)
                    # Convert string keys back to int
                    self._memory = {int(k): v for k, v in data.items()}
                log.tree("User Memory Loaded", [
                    ("Users", str(len(self._memory))),
                ], emoji="🧠")
        except Exception as e:
            log.tree("User Memory Load Failed", [
                ("Error", str(e)[:50]),
            ], emoji="⚠️")
            self._memory = {}

    def _save(self) -> None:
        """Save memory to file."""
        try:
            self.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.DATA_FILE, "w") as f:
                json.dump(self._memory, f, indent=2)
        except Exception as e:
            log.tree("User Memory Save Failed", [
                ("Error", str(e)[:50]),
            ], emoji="⚠️")

    def _get_user(self, user_id: int) -> dict:
        """Get or create user memory entry."""
        if user_id not in self._memory:
            # Check if we need to evict old users
            self._evict_if_needed()

            self._memory[user_id] = {
                "topics": defaultdict(int),
                "frustration_count": 0,
                "positive_count": 0,
                "interaction_count": 0,
                "last_interaction": 0,
            }
        return self._memory[user_id]

    def _evict_if_needed(self) -> None:
        """Evict least-recently-used users if at capacity."""
        if len(self._memory) < self.MAX_USERS:
            return

        # Sort by last_interaction (oldest first)
        sorted_users = sorted(
            self._memory.items(),
            key=lambda x: x[1].get("last_interaction", 0)
        )

        # Evict oldest users
        evicted = 0
        for user_id, _ in sorted_users[:self.EVICT_COUNT]:
            del self._memory[user_id]
            evicted += 1

        log.tree("User Memory Eviction", [
            ("Evicted", str(evicted)),
            ("Remaining", str(len(self._memory))),
        ], emoji="🧹")

    def record_interaction(self, user_id: int, message: str) -> None:
        """
        Record a user interaction and extract patterns.

        Args:
            user_id: Discord user ID
            message: The user's message content
        """
        user = self._get_user(user_id)
        msg_lower = message.lower()

        # Update interaction count
        user["interaction_count"] = user.get("interaction_count", 0) + 1
        user["last_interaction"] = time.time()

        # Detect topics
        topics_found = []
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if any(kw in msg_lower for kw in keywords):
                if isinstance(user["topics"], dict):
                    user["topics"][topic] = user["topics"].get(topic, 0) + 1
                else:
                    user["topics"] = {topic: 1}
                topics_found.append(topic)

        # Detect frustration
        frustration_detected = any(word in msg_lower for word in self.FRUSTRATION_WORDS)
        if frustration_detected:
            user["frustration_count"] = user.get("frustration_count", 0) + 1

        # Detect positive sentiment
        positive_detected = any(word in msg_lower for word in self.POSITIVE_WORDS)
        if positive_detected:
            user["positive_count"] = user.get("positive_count", 0) + 1

        # Save periodically (every 5 interactions)
        if user["interaction_count"] % 5 == 0:
            self._save()

        if topics_found or frustration_detected or positive_detected:
            log.tree("User Interaction Recorded", [
                ("User ID", str(user_id)),
                ("Topics", ", ".join(topics_found) if topics_found else "None"),
                ("Frustrated", "Yes" if frustration_detected else "No"),
                ("Positive", "Yes" if positive_detected else "No"),
                ("Total Interactions", str(user["interaction_count"])),
            ], emoji="📊")

    def get_user_context(self, user_id: int) -> str:
        """
        Get context string about a user's patterns.

        Returns context for the AI about this user's history.
        """
        if user_id not in self._memory:
            return ""

        user = self._memory[user_id]
        context_parts = []

        # Get top topics
        topics = user.get("topics", {})
        if topics:
            # Sort by count
            sorted_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)
            top_topics = [t[0] for t in sorted_topics[:3] if t[1] >= 2]
            if top_topics:
                context_parts.append(f"This user frequently asks about: {', '.join(top_topics)}")

        # Check frustration ratio
        interactions = user.get("interaction_count", 0)
        frustration = user.get("frustration_count", 0)
        positive = user.get("positive_count", 0)

        if interactions >= 3:
            frustration_ratio = frustration / interactions
            if frustration_ratio > 0.5:
                context_parts.append("USER MOOD: This user seems frequently frustrated. Be a bit more patient and helpful, less toxic.")
            elif frustration_ratio > 0.3:
                context_parts.append("USER MOOD: This user has been frustrated before. Don't be too harsh.")

        # Note if they're usually positive
        if interactions >= 3 and positive >= 2:
            positive_ratio = positive / interactions
            if positive_ratio > 0.3:
                context_parts.append("This user is usually positive and appreciative. You can be more friendly.")

        if not context_parts:
            return ""

        return "USER HISTORY: " + " ".join(context_parts)

    def detect_current_sentiment(self, message: str) -> str:
        """
        Detect sentiment in the current message.

        Returns context string about current emotional state.
        """
        msg_lower = message.lower()

        # Count frustration indicators
        frustration_count = sum(1 for word in self.FRUSTRATION_WORDS if word in msg_lower)

        # Check for caps (shouting)
        caps_ratio = sum(1 for c in message if c.isupper()) / max(len(message), 1)

        # Check for excessive punctuation
        excessive_punct = message.count("!") >= 3 or message.count("?") >= 3

        if frustration_count >= 2 or (frustration_count >= 1 and (caps_ratio > 0.5 or excessive_punct)):
            log.tree("High Frustration Detected", [
                ("Indicators", str(frustration_count)),
                ("Caps Ratio", f"{caps_ratio:.1%}"),
                ("Excessive Punct", str(excessive_punct)),
            ], emoji="😤")
            return "CURRENT MOOD: User seems frustrated/upset right now. Tone down the toxicity, be more helpful and patient."
        elif frustration_count == 1:
            return "CURRENT MOOD: User might be a bit frustrated. Don't be too harsh."

        # Check for positive
        positive_count = sum(1 for word in self.POSITIVE_WORDS if word in msg_lower)
        if positive_count >= 1:
            return ""  # No special context needed for positive

        return ""

    def get_stats(self) -> dict:
        """Get memory statistics."""
        return {
            "total_users": len(self._memory),
            "total_interactions": sum(u.get("interaction_count", 0) for u in self._memory.values()),
        }


# Global instance
user_memory = UserMemory()
