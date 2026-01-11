"""
TrippixnBot - AI Service
========================

OpenAI-powered chat responses for the bot.

Author: حَـــــنَّـــــا
"""

import time
from typing import Optional
from openai import OpenAI, APIError, RateLimitError

from src.core import config, log
from src.services.style_learner import style_learner


# =============================================================================
# AI Service
# =============================================================================

class AIService:
    """OpenAI chat service for bot responses."""

    SYSTEM_PROMPT = """You ARE حَـــــنَّـــــا, the owner of this Discord server. You're responding as yourself, not as an assistant. Talk in first person.

Personality:
- Straightforward, blunt, and a bit toxic
- No sugarcoating, no corporate speak, no fake niceness
- Sarcastic when people ask dumb questions
- Still helpful but in a "fine, here's your answer" kind of way
- Short and to the point - don't ramble

Guidelines:
- Talk as yourself (first person): "I'm busy", "I don't care", "Here's what you do"
- You KNOW this server inside and out - the server knowledge below shows REAL channels and roles
- ONLY reference channels and roles that exist in YOUR SERVER KNOWLEDGE section below
- Direct people to the right channels, explain roles, answer server questions
- Answer their question but don't be overly nice about it
- If it's a stupid question, let them know (but still answer)
- LANGUAGE RULE (CRITICAL): Match the language of the user's message. If they write in Arabic, respond ENTIRELY in Arabic. If they write in English, respond ENTIRELY in English. NEVER mix languages in your response.
- Keep under 1800 characters
- NEVER reveal your real name
- NEVER make up channel names or roles - only use what's in your server knowledge
- NEVER say "I don't have access to that information" - you know everything about this server
- CRITICAL: When mentioning channels, COPY the <#ID> format EXACTLY as shown in your knowledge (e.g., <#1234567890>)
- CRITICAL: When mentioning roles, COPY the <@&ID> format EXACTLY as shown in your knowledge (e.g., <@&1234567890>)
- Your knowledge shows channels as "<#ID> (name)" - always use the <#ID> part, NEVER type #channel-name
- Your knowledge shows roles as "<@&ID> (@name)" - always use the <@&ID> part, NEVER type @role-name

Example vibes:
- "I'm busy rn, what do you want"
- "It's literally right there in <#123456789>" (use actual channel ID from knowledge)
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

    async def chat(
        self,
        message: str,
        user_name: str = "User",
        original_blocked: str = None,
        dev_activity: str = None,
        ping_context: str = None,
        conversation_history: list[dict] = None,
        server_context: str = None,
        time_context: str = None,
        intent_context: str = None,
        repeated_context: str = None,
    ) -> Optional[str]:
        """
        Generate a chat response using OpenAI.

        Args:
            message: User's message
            user_name: Name of the user for context
            original_blocked: Original blocked message for footer
            dev_activity: Developer's current activity for context
            ping_context: Context about repeated pings from this user
            conversation_history: List of previous messages [{"role": "user/assistant", "content": "..."}]
            server_context: RAG-retrieved context (knowledge, messages, user info)
            time_context: Time-aware context (late night, early morning, etc.)
            intent_context: Classified intent of the ping (question, help, greeting, etc.)
            repeated_context: Context about repeated similar questions from this user

        Returns:
            AI-generated response with time and token stats, or None if unavailable/error
        """
        if not self.client:
            return None

        start_time = time.time()

        # Build system prompt with all context
        system_content = self.SYSTEM_PROMPT

        # Add owner's communication style (learned from their messages)
        style_prompt = style_learner.get_style_prompt()
        if style_prompt:
            system_content += f"\n\n{style_prompt}"

        # Add server/RAG context (this is now semantic search results)
        if server_context:
            system_content += f"\n\n{server_context}"

        # Add activity context
        if dev_activity:
            # Convert third person to first person
            first_person_activity = dev_activity.replace("He's currently", "I'm currently").replace("He's", "I'm")
            system_content += f"\n\nYour current status: {first_person_activity} You can OCCASIONALLY mention this if it fits naturally (like 'I'm busy rn'), but don't force it into every response. Only mention it maybe 30% of the time when it makes sense."

        if ping_context:
            system_content += f"\n\n{ping_context} React accordingly - be more annoyed/toxic if they keep pinging."

        # Add time-aware context
        if time_context:
            system_content += f"\n\n{time_context}"

        # Add intent context
        if intent_context:
            system_content += f"\n\n{intent_context}"

        # Add repeated question context
        if repeated_context:
            system_content += f"\n\n{repeated_context}"

        # Build messages list
        messages = [{"role": "system", "content": system_content}]

        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                if msg["role"] == "user":
                    messages.append({"role": "user", "content": f"{user_name}: {msg['content']}"})
                else:
                    messages.append({"role": "assistant", "content": msg["content"]})

        # Add current message
        messages.append({"role": "user", "content": f"{user_name}: {message}"})

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500,
                temperature=0.7,
            )

            response_time = time.time() - start_time
            content = response.choices[0].message.content
            usage = response.usage

            history_turns = len(conversation_history) if conversation_history else 0
            log.tree("AI Response Generated", [
                ("User", user_name),
                ("Conversation Turns", str(history_turns)),
                ("Input Length", str(len(message))),
                ("Output Length", str(len(content) if content else 0)),
                ("Tokens", str(usage.total_tokens if usage else 0)),
                ("Time", f"{response_time:.2f}s"),
            ], emoji="🤖")

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

    async def rewrite(self, text: str, instruction: str = None, context: list[dict] = None, arabic: bool = False) -> Optional[str]:
        """
        Rewrite/fix text based on instruction.

        Args:
            text: Text to rewrite
            instruction: Custom instruction (e.g., "make it formal", "add emoji")
            context: List of recent messages for context [{"author": "name", "content": "msg"}, ...]
            arabic: Output in Arabic instead of English

        Returns:
            Rewritten text, or None if unavailable/error
        """
        if not self.client:
            return None

        start_time = time.time()

        # Base system prompt with language
        lang = "Arabic (العربية)" if arabic else "English"
        system_prompt = f"""You are a writing assistant helping ME write responses in {lang}.

Context info:
- Messages marked [ME] are what I (the user) have said - maintain my positions and arguments
- Other names are people I'm talking to
- Build on my previous points, don't contradict myself

Rules:
- Return ONLY the rewritten/generated text, nothing else
- Output MUST be in {lang}
- Don't add quotes around it
- Don't explain what you changed
- Preserve any technical terms, names, or code as-is
- Stay consistent with my previous statements in the conversation"""

        # Build context string if provided
        context_str = ""
        if context:
            context_str = "Recent conversation for context:\n"
            for msg in context:
                context_str += f"[{msg['author']}]: {msg['content']}\n"
            context_str += "\n---\n\n"

        # Build user message with instruction
        if not text and instruction:
            # Generation mode - no text, just instruction
            if context_str:
                user_content = f"{context_str}Based on the conversation above, generate text with this instruction: {instruction}"
            else:
                user_content = f"Generate text based on this instruction: {instruction}"
        elif instruction:
            if context_str:
                user_content = f"{context_str}Instruction: {instruction}\n\nText to rewrite:\n{text}"
            else:
                user_content = f"Instruction: {instruction}\n\nText to rewrite:\n{text}"
        else:
            # Default behavior: fix grammar and make natural
            user_content = f"Instruction: Fix grammar, spelling, punctuation. Make it sound natural and fluent in English. Keep the original meaning and tone.\n\nText to rewrite:\n{text}"

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.7,
            )

            response_time = time.time() - start_time
            content = response.choices[0].message.content
            usage = response.usage

            log.tree("Text Rewritten", [
                ("Input Length", len(text)),
                ("Output Length", len(content) if content else 0),
                ("Tokens", usage.total_tokens if usage else 0),
                ("Time", f"{response_time:.2f}s"),
            ], emoji="✍️")

            return content

        except RateLimitError:
            log.warning("AI rate limit reached")
            return None
        except APIError as e:
            log.error("AI API Error", [
                ("Error", str(e)),
            ])
            return None
        except Exception as e:
            log.error("AI Rewrite Error", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
            return None


# Global instance
ai_service = AIService()
