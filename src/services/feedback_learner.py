"""
TrippixnBot - Feedback Learner Service
======================================

Tracks and learns from:
- Owner corrections (when owner responds after bot)
- Reaction feedback (thumbs up/down on bot messages)
- FAQ candidates (frequently asked similar questions)

Author: حَـــــنَّـــــا
"""

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core import config, log


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Correction:
    """A correction from the owner."""
    timestamp: float
    channel_id: int
    original_question: str
    bot_response: str
    owner_correction: str
    bot_message_id: int


@dataclass
class ReactionFeedback:
    """Feedback from a reaction on bot message."""
    timestamp: float
    message_id: int
    channel_id: int
    user_id: int
    emoji: str
    is_positive: bool
    bot_response: str


@dataclass
class FAQCandidate:
    """A frequently asked question candidate."""
    question_variants: list[str] = field(default_factory=list)
    best_answer: str = ""
    frequency: int = 0
    last_asked: float = 0


# =============================================================================
# Feedback Learner Service
# =============================================================================

class FeedbackLearner:
    """
    Central service for tracking feedback and learning from it.

    Tracks:
    - Owner corrections after bot responses
    - Reaction feedback on bot messages
    - FAQ candidates from similar questions
    - Bot message history for reaction tracking
    """

    DATA_DIR = Path(__file__).parent.parent.parent / "data"
    FEEDBACK_FILE = DATA_DIR / "feedback.json"

    # Positive and negative reaction emojis
    POSITIVE_EMOJIS = {"👍", "😂", "❤️", "🔥", "💯", "✅", "🙏", "😊", "🤣", "👏"}
    NEGATIVE_EMOJIS = {"👎", "😐", "❌", "😒", "🙄", "💀", "😑", "👀"}

    # Correction detection window (2 minutes)
    CORRECTION_WINDOW = 120

    # Max items to keep
    MAX_CORRECTIONS = 100
    MAX_REACTIONS = 500
    MAX_BOT_MESSAGES = 50

    def __init__(self):
        self._corrections: list[Correction] = []
        self._reactions: list[ReactionFeedback] = []
        self._faq_candidates: dict[str, FAQCandidate] = {}

        # Track recent bot messages for reaction detection
        # {message_id: {"channel_id": int, "response": str, "timestamp": float}}
        self._bot_messages: dict[int, dict] = {}

        # Track last bot response per channel for correction detection
        # {channel_id: {"message_id": int, "response": str, "question": str, "timestamp": float}}
        self._last_bot_response: dict[int, dict] = {}

        self._initialized = False
        self._dirty = False
        self._save_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def setup(self) -> bool:
        """Initialize the feedback learner."""
        self.DATA_DIR.mkdir(exist_ok=True)
        self._load_data()
        self._initialized = True

        # Start periodic save task
        self._save_task = asyncio.create_task(self._periodic_save())

        log.tree("Feedback Learner Initialized", [
            ("Corrections", str(len(self._corrections))),
            ("Reactions", str(len(self._reactions))),
            ("FAQ Candidates", str(len(self._faq_candidates))),
        ], emoji="📊")

        return True

    def stop(self) -> None:
        """Stop the feedback learner."""
        if self._save_task:
            self._save_task.cancel()
            self._save_task = None

        self._save_data()

        log.tree("Feedback Learner Stopped", [
            ("Corrections Saved", str(len(self._corrections))),
            ("Reactions Saved", str(len(self._reactions))),
        ], emoji="🛑")

    def _load_data(self) -> None:
        """Load feedback data from disk."""
        if self.FEEDBACK_FILE.exists():
            try:
                with open(self.FEEDBACK_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Load corrections
                for c in data.get("corrections", []):
                    self._corrections.append(Correction(
                        timestamp=c["timestamp"],
                        channel_id=c["channel_id"],
                        original_question=c["original_question"],
                        bot_response=c["bot_response"],
                        owner_correction=c["owner_correction"],
                        bot_message_id=c.get("bot_message_id", 0),
                    ))

                # Load reactions
                for r in data.get("reactions", []):
                    self._reactions.append(ReactionFeedback(
                        timestamp=r["timestamp"],
                        message_id=r["message_id"],
                        channel_id=r["channel_id"],
                        user_id=r["user_id"],
                        emoji=r["emoji"],
                        is_positive=r["is_positive"],
                        bot_response=r["bot_response"],
                    ))

                # Load FAQ candidates
                for key, faq in data.get("faq_candidates", {}).items():
                    self._faq_candidates[key] = FAQCandidate(
                        question_variants=faq["question_variants"],
                        best_answer=faq.get("best_answer", ""),
                        frequency=faq["frequency"],
                        last_asked=faq.get("last_asked", 0),
                    )

                log.tree("Feedback Data Loaded", [
                    ("Corrections", str(len(self._corrections))),
                    ("Reactions", str(len(self._reactions))),
                    ("FAQs", str(len(self._faq_candidates))),
                ], emoji="📂")

            except Exception as e:
                log.tree("Feedback Load Failed", [
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")
        else:
            log.tree("Feedback Data File", [
                ("Status", "No existing file, starting fresh"),
            ], emoji="📄")

    def _save_data(self) -> None:
        """Save feedback data to disk."""
        try:
            data = {
                "corrections": [
                    {
                        "timestamp": c.timestamp,
                        "channel_id": c.channel_id,
                        "original_question": c.original_question,
                        "bot_response": c.bot_response,
                        "owner_correction": c.owner_correction,
                        "bot_message_id": c.bot_message_id,
                    }
                    for c in self._corrections[-self.MAX_CORRECTIONS:]
                ],
                "reactions": [
                    {
                        "timestamp": r.timestamp,
                        "message_id": r.message_id,
                        "channel_id": r.channel_id,
                        "user_id": r.user_id,
                        "emoji": r.emoji,
                        "is_positive": r.is_positive,
                        "bot_response": r.bot_response,
                    }
                    for r in self._reactions[-self.MAX_REACTIONS:]
                ],
                "faq_candidates": {
                    key: {
                        "question_variants": faq.question_variants,
                        "best_answer": faq.best_answer,
                        "frequency": faq.frequency,
                        "last_asked": faq.last_asked,
                    }
                    for key, faq in self._faq_candidates.items()
                },
                "updated_at": datetime.now().isoformat(),
            }

            with open(self.FEEDBACK_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self._dirty = False

            log.tree("Feedback Data Saved", [
                ("Corrections", str(len(self._corrections))),
                ("Reactions", str(len(self._reactions))),
            ], emoji="💾")

        except Exception as e:
            log.tree("Feedback Save Failed", [
                ("Error", str(e)[:50]),
            ], emoji="⚠️")

    async def _periodic_save(self) -> None:
        """Periodically save data to disk."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                if self._dirty:
                    async with self._lock:
                        self._save_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.tree("Feedback Save Error", [
                    ("Error", str(e)[:50]),
                ], emoji="⚠️")

    # =========================================================================
    # Bot Message Tracking
    # =========================================================================

    def track_bot_response(
        self,
        message_id: int,
        channel_id: int,
        response: str,
        original_question: str,
    ) -> None:
        """Track a bot response for reaction and correction detection."""
        now = time.time()

        # Store in bot messages dict for reaction tracking
        self._bot_messages[message_id] = {
            "channel_id": channel_id,
            "response": response,
            "question": original_question,
            "timestamp": now,
        }

        # Store as last response in channel for correction tracking
        self._last_bot_response[channel_id] = {
            "message_id": message_id,
            "response": response,
            "question": original_question,
            "timestamp": now,
        }

        # Clean old bot messages
        self._cleanup_old_messages()

    def _cleanup_old_messages(self) -> None:
        """Remove old bot message tracking."""
        now = time.time()
        cutoff = now - 3600  # 1 hour

        # Clean bot messages
        old_ids = [
            mid for mid, data in self._bot_messages.items()
            if data["timestamp"] < cutoff
        ]
        for mid in old_ids:
            del self._bot_messages[mid]

        # Keep only most recent per channel for corrections
        if len(self._bot_messages) > self.MAX_BOT_MESSAGES:
            sorted_msgs = sorted(
                self._bot_messages.items(),
                key=lambda x: x[1]["timestamp"],
                reverse=True
            )
            self._bot_messages = dict(sorted_msgs[:self.MAX_BOT_MESSAGES])

    def is_bot_message(self, message_id: int) -> bool:
        """Check if a message ID is a tracked bot message."""
        return message_id in self._bot_messages

    def get_bot_message(self, message_id: int) -> Optional[dict]:
        """Get bot message data by ID."""
        return self._bot_messages.get(message_id)

    # =========================================================================
    # Correction Detection
    # =========================================================================

    def check_for_correction(
        self,
        channel_id: int,
        owner_message: str,
    ) -> Optional[Correction]:
        """
        Check if owner message is a correction to a recent bot response.

        Returns Correction if detected, None otherwise.
        """
        if channel_id not in self._last_bot_response:
            return None

        last = self._last_bot_response[channel_id]
        now = time.time()

        # Check if within correction window
        if now - last["timestamp"] > self.CORRECTION_WINDOW:
            return None

        # Create and store correction
        correction = Correction(
            timestamp=now,
            channel_id=channel_id,
            original_question=last["question"],
            bot_response=last["response"],
            owner_correction=owner_message,
            bot_message_id=last["message_id"],
        )

        self._corrections.append(correction)
        self._dirty = True

        # Clear last response to prevent duplicate corrections
        del self._last_bot_response[channel_id]

        log.tree("Owner Correction Detected", [
            ("Channel", str(channel_id)),
            ("Bot Said", last["response"][:40] + "..."),
            ("Owner Said", owner_message[:40] + "..."),
        ], emoji="✏️")

        return correction

    def get_correction_patterns(self) -> list[dict]:
        """Get recent corrections for style learning."""
        return [
            {
                "bad_response": c.bot_response,
                "good_response": c.owner_correction,
                "question": c.original_question,
            }
            for c in self._corrections[-20:]  # Last 20 corrections
        ]

    # =========================================================================
    # Reaction Feedback
    # =========================================================================

    def record_reaction(
        self,
        message_id: int,
        user_id: int,
        emoji: str,
    ) -> Optional[ReactionFeedback]:
        """
        Record a reaction on a bot message.

        Returns ReactionFeedback if valid, None otherwise.
        """
        bot_msg = self._bot_messages.get(message_id)
        if not bot_msg:
            return None

        # Determine if positive or negative
        is_positive = emoji in self.POSITIVE_EMOJIS
        is_negative = emoji in self.NEGATIVE_EMOJIS

        if not is_positive and not is_negative:
            return None  # Neutral/unknown emoji

        feedback = ReactionFeedback(
            timestamp=time.time(),
            message_id=message_id,
            channel_id=bot_msg["channel_id"],
            user_id=user_id,
            emoji=emoji,
            is_positive=is_positive,
            bot_response=bot_msg["response"],
        )

        self._reactions.append(feedback)
        self._dirty = True

        log.tree("Reaction Feedback Recorded", [
            ("Emoji", emoji),
            ("Type", "Positive" if is_positive else "Negative"),
            ("Response", bot_msg["response"][:40] + "..."),
        ], emoji="👍" if is_positive else "👎")

        return feedback

    def get_feedback_stats(self) -> dict:
        """Get reaction feedback statistics."""
        positive = sum(1 for r in self._reactions if r.is_positive)
        negative = len(self._reactions) - positive

        return {
            "total": len(self._reactions),
            "positive": positive,
            "negative": negative,
            "ratio": positive / max(1, len(self._reactions)),
        }

    # =========================================================================
    # FAQ Tracking
    # =========================================================================

    def track_question(self, question: str, answer: str = "") -> None:
        """Track a question for FAQ detection."""
        # Simple normalization
        key = question.lower().strip()[:100]

        if key not in self._faq_candidates:
            self._faq_candidates[key] = FAQCandidate(
                question_variants=[question],
                best_answer=answer,
                frequency=1,
                last_asked=time.time(),
            )
        else:
            faq = self._faq_candidates[key]
            faq.frequency += 1
            faq.last_asked = time.time()
            if question not in faq.question_variants:
                faq.question_variants.append(question)
            if answer and not faq.best_answer:
                faq.best_answer = answer

        self._dirty = True

    def get_frequent_questions(self, min_frequency: int = 3) -> list[FAQCandidate]:
        """Get questions asked frequently."""
        return [
            faq for faq in self._faq_candidates.values()
            if faq.frequency >= min_frequency
        ]

    # =========================================================================
    # Stats
    # =========================================================================

    def get_stats(self) -> dict:
        """Get feedback learner statistics."""
        feedback_stats = self.get_feedback_stats()
        frequent_faqs = self.get_frequent_questions()

        return {
            "initialized": self._initialized,
            "corrections_count": len(self._corrections),
            "reactions_count": len(self._reactions),
            "positive_reactions": feedback_stats["positive"],
            "negative_reactions": feedback_stats["negative"],
            "tracked_messages": len(self._bot_messages),
            "faq_candidates": len(self._faq_candidates),
            "frequent_faqs": len(frequent_faqs),
        }


# Global instance
feedback_learner = FeedbackLearner()
