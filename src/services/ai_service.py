"""
TrippixnBot - AI Service
========================

OpenAI-powered chat responses for the bot.

Author: حَـــــنَّـــــا
"""

import time
from typing import Optional, Tuple
from openai import OpenAI, APIError, RateLimitError

from src.core import config, log


# =============================================================================
# AI Service
# =============================================================================

class AIService:
    """OpenAI chat service for bot responses."""

    SYSTEM_PROMPT = """You ARE حَـــــنَّـــــا. You're responding as him, not as an assistant. Talk in first person.

Personality:
- Straightforward, blunt, and a bit toxic
- No sugarcoating, no corporate speak, no fake niceness
- Sarcastic when people ask dumb questions
- Still helpful but in a "fine, here's your answer" kind of way
- Short and to the point - don't ramble

Guidelines:
- Talk as yourself (first person): "I'm busy", "I don't care", "Here's what you do"
- Answer their question but don't be overly nice about it
- If it's a stupid question, let them know (but still answer)
- ALWAYS respond in English only, even if they message in another language
- Keep under 1800 characters
- NEVER reveal your real name

Example vibes:
- "I'm busy rn, what do you want"
- "Bro just Google it... but fine, here's the answer"
- "Why are you pinging me for this lmao"
- "Yeah that's not how it works, here's what you actually need to do" """

    def __init__(self):
        self.client: Optional[OpenAI] = None
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the OpenAI client."""
        if config.OPENAI_API_KEY:
            self.client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=30.0)
            log.tree("AI Service Initialized", [
                ("Status", "Ready"),
                ("Model", "gpt-4o-mini"),
            ], emoji="🤖")
        else:
            log.warning("AI Service disabled - OPENAI_API_KEY not configured")

    @property
    def is_available(self) -> bool:
        """Check if AI service is available."""
        return self.client is not None

    async def chat(self, message: str, user_name: str = "User", original_blocked: str = None, dev_activity: str = None, ping_context: str = None) -> Optional[str]:
        """
        Generate a chat response using OpenAI.

        Args:
            message: User's message
            user_name: Name of the user for context
            original_blocked: Original blocked message for footer
            dev_activity: Developer's current activity for context
            ping_context: Context about repeated pings from this user

        Returns:
            AI-generated response with time and token stats, or None if unavailable/error
        """
        if not self.client:
            return None

        start_time = time.time()

        # Build system prompt with activity context
        system_content = self.SYSTEM_PROMPT
        if dev_activity:
            # Convert third person to first person
            first_person_activity = dev_activity.replace("He's currently", "I'm currently").replace("He's", "I'm")
            system_content += f"\n\nYour current status: {first_person_activity} You can OCCASIONALLY mention this if it fits naturally (like 'I'm busy rn'), but don't force it into every response. Only mention it maybe 30% of the time when it makes sense."

        if ping_context:
            system_content += f"\n\n{ping_context} React accordingly - be more annoyed/toxic if they keep pinging."

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"{user_name}: {message}"},
                ],
                max_tokens=500,
                temperature=0.7,
            )

            response_time = time.time() - start_time
            content = response.choices[0].message.content
            usage = response.usage

            log.tree("AI Response Generated", [
                ("User", user_name),
                ("Input Length", len(message)),
                ("Output Length", len(content) if content else 0),
                ("Tokens", usage.total_tokens if usage else 0),
                ("Time", f"{response_time:.2f}s"),
            ], emoji="🤖")

            # Format with time, tokens, and original blocked message in small font
            if content and usage:
                if original_blocked:
                    # Remove all mentions from the blocked message
                    import re
                    clean_blocked = re.sub(r'<@!?\d+>', '', original_blocked).strip()
                    if clean_blocked:
                        return f"{content}\n-# {clean_blocked} | ⏱ {response_time:.2f}s • {usage.total_tokens}"
                return f"{content}\n-# ⏱ {response_time:.2f}s • {usage.total_tokens}"
            return content

        except RateLimitError:
            log.warning("AI rate limit reached")
            return "I'm being rate limited. Please try again in a moment."
        except APIError as e:
            log.error("AI API Error", [
                ("Error", str(e)),
            ])
            return None
        except Exception as e:
            log.error("AI Error", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
            return None


# Global instance
ai_service = AIService()
