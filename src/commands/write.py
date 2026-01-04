"""
TrippixnBot - Write Command
===========================

Owner-only AI writing assistant.
- Rewrite/fix text
- Generate responses
- Context-aware
- Send as me

Author: حَـــــنَّـــــا
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from src.core import config, log
from src.services import ai_service


# =============================================================================
# Personalities (for dropdown in embed)
# =============================================================================

PERSONALITIES = {
    "me": {
        "name": "Me (Default)",
        "emoji": "🎯",
        "prompt": "Write in a short, dry, direct style. Get to the point quickly. No fluff, no excessive politeness. Matter-of-fact tone.",
    },
    "professional": {
        "name": "Professional",
        "emoji": "💼",
        "prompt": "Write in a professional, polished tone. Be clear, respectful, and formal. Suitable for work contexts.",
    },
    "friendly": {
        "name": "Friendly",
        "emoji": "😊",
        "prompt": "Write in a warm, friendly tone. Be approachable and positive. Add a touch of personality.",
    },
    "assertive": {
        "name": "Assertive",
        "emoji": "💪",
        "prompt": "Write in a confident, assertive tone. Be direct and firm but not rude.",
    },
    "academic": {
        "name": "Academic",
        "emoji": "🎓",
        "prompt": "Write in a scholarly, well-reasoned style. Use logical arguments, cite reasoning, and maintain intellectual rigor. Sound educated and articulate.",
    },
    "diplomatic": {
        "name": "Diplomatic",
        "emoji": "🕊️",
        "prompt": "Write in a balanced, considerate tone. Acknowledge other perspectives while making your point. Find common ground where possible. Be tactful.",
    },
    "sarcastic": {
        "name": "Sarcastic",
        "emoji": "😏",
        "prompt": "Write with wit and irony. Be clever and pointed. Use sarcasm effectively but don't be mean-spirited. Sharp humor.",
    },
}


# =============================================================================
# Copy Modal
# =============================================================================

class CopyModal(discord.ui.Modal, title="Copy Text"):
    """Modal to easily copy the rewritten text."""

    text_field = discord.ui.TextInput(
        label="Rewritten Text (select all & copy)",
        style=discord.TextStyle.paragraph,
        required=False,
    )

    def __init__(self, text: str):
        super().__init__()
        # Truncate if too long for modal (max 4000)
        self.text_field.default = text[:4000] if len(text) > 4000 else text

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()


class EditInstructionModal(discord.ui.Modal, title="Edit Instruction"):
    """Modal to edit the instruction and regenerate."""

    instruction_field = discord.ui.TextInput(
        label="Instruction",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., 'make it shorter', 'add more detail', 'be more aggressive'",
        required=True,
    )

    def __init__(self, view: "RewriteView"):
        super().__init__()
        self.rewrite_view = view
        # Pre-fill with current instruction
        if view.instruction:
            self.instruction_field.default = view.instruction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        new_instruction = self.instruction_field.value

        # Combine personality with new instruction
        personality = PERSONALITIES[self.rewrite_view.current_personality]
        combined = f"{personality['prompt']} {new_instruction}"

        # Regenerate with new instruction
        result = await ai_service.rewrite(
            self.rewrite_view.original_text,
            combined,
            self.rewrite_view.context,
            self.rewrite_view.arabic
        )

        if not result:
            log.tree("Edit Instruction Failed", [
                ("Instruction", new_instruction[:50]),
                ("Reason", "AI service returned None"),
            ], emoji="❌")
            await interaction.followup.send("Failed to regenerate.", ephemeral=True)
            return

        # Update stored text and instruction
        self.rewrite_view.rewritten_text = result
        self.rewrite_view.instruction = new_instruction

        # Build new embed
        embed = _build_embed(self.rewrite_view.original_text, result, new_instruction, self.rewrite_view.arabic)
        footer_parts = [f"Personality: {personality['name']}"]
        if new_instruction:
            footer_parts.append(f"Instruction: {new_instruction[:40]}")
        if self.rewrite_view.context:
            footer_parts.append(f"Context: {len(self.rewrite_view.context)} msgs")
        if self.rewrite_view.arabic:
            footer_parts.append("Arabic")
        embed.set_footer(text=" | ".join(footer_parts))

        await interaction.edit_original_response(embed=embed, view=self.rewrite_view)
        log.tree("Instruction Edited", [
            ("New Instruction", new_instruction[:50]),
            ("Personality", personality["name"]),
            ("Result Length", len(result)),
        ], emoji="✏️")


# =============================================================================
# Rewrite View (Buttons)
# =============================================================================

class PersonalitySelect(discord.ui.Select):
    """Dropdown to select personality/tone."""

    def __init__(self, current: str = "me"):
        options = [
            discord.SelectOption(
                label=p["name"],
                value=key,
                emoji=p["emoji"],
                default=(key == current),
            )
            for key, p in PERSONALITIES.items()
        ]
        super().__init__(
            placeholder="Change personality...",
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        """Regenerate with selected personality."""
        await interaction.response.defer()

        view: RewriteView = self.view
        selected = self.values[0]
        personality = PERSONALITIES[selected]

        # Combine personality with original instruction
        personality_prompt = personality["prompt"]
        if view.instruction:
            combined = f"{personality_prompt} {view.instruction}"
        else:
            combined = personality_prompt

        # Regenerate with new personality
        result = await ai_service.rewrite(view.original_text, combined, view.context, view.arabic)

        if not result:
            log.tree("Personality Change Failed", [
                ("Personality", personality["name"]),
                ("Reason", "AI service returned None"),
            ], emoji="❌")
            await interaction.followup.send("Failed to regenerate.", ephemeral=True)
            return

        # Update stored text and personality
        view.rewritten_text = result
        view.current_personality = selected

        # Update dropdown default
        for option in self.options:
            option.default = (option.value == selected)

        # Build new embed
        embed = _build_embed(view.original_text, result, view.instruction, view.arabic)
        footer_parts = [f"Personality: {personality['name']}"]
        if view.context:
            footer_parts.append(f"Context: {len(view.context)} msgs")
        if view.arabic:
            footer_parts.append("Arabic")
        embed.set_footer(text=" | ".join(footer_parts))

        await interaction.edit_original_response(embed=embed, view=view)
        log.tree("Personality Changed", [
            ("New Personality", personality["name"]),
            ("Result Length", len(result)),
            ("Arabic", view.arabic),
        ], emoji="🎭")


class RewriteView(discord.ui.View):
    """View with Send, Copy, Regenerate, and Personality dropdown."""

    def __init__(
        self,
        original_text: str,
        rewritten_text: str,
        instruction: Optional[str],
        owner_id: int,
        trigger_message: Optional[discord.Message] = None,
        context: Optional[list] = None,
        arabic: bool = False,
    ):
        super().__init__(timeout=300)  # 5 minute timeout
        self.original_text = original_text
        self.rewritten_text = rewritten_text
        self.instruction = instruction
        self.owner_id = owner_id
        self.trigger_message = trigger_message
        self.context = context
        self.arabic = arabic
        self.current_personality = "me"  # Default personality

        # Add personality dropdown
        self.add_item(PersonalitySelect(current="me"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Only owner can use buttons."""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't yours.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Send (as bot)", style=discord.ButtonStyle.secondary, emoji="📤", row=1)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Send the rewritten text to the channel (shows APP tag)."""
        await interaction.response.defer()

        # Send as a regular message (not ephemeral)
        await interaction.channel.send(self.rewritten_text)

        # Update the original message to show it was sent
        button.disabled = True
        button.label = "Sent!"
        await interaction.edit_original_response(view=self)

        channel_name = interaction.channel.name if hasattr(interaction.channel, 'name') else 'DM'
        log.tree("Text Sent", [
            ("Channel", f"#{channel_name}"),
            ("Length", len(self.rewritten_text)),
            ("Personality", self.current_personality),
        ], emoji="📤")

    @discord.ui.button(label="Copy", style=discord.ButtonStyle.success, emoji="📋", row=1)
    async def copy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to copy the text (paste it yourself for no APP tag)."""
        modal = CopyModal(self.rewritten_text)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Regenerate", style=discord.ButtonStyle.primary, emoji="🔄", row=1)
    async def regenerate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Regenerate with the same settings."""
        await interaction.response.defer()

        # Regenerate (with context and language if available)
        result = await ai_service.rewrite(self.original_text, self.instruction, self.context, self.arabic)

        if not result:
            log.tree("Regenerate Failed", [
                ("Instruction", self.instruction[:50] if self.instruction else "None"),
                ("Reason", "AI service returned None"),
            ], emoji="❌")
            await interaction.followup.send("Failed to regenerate.", ephemeral=True)
            return

        # Update stored text
        self.rewritten_text = result

        # Build new embed
        embed = _build_embed(self.original_text, result, self.instruction, self.arabic)
        await interaction.edit_original_response(embed=embed, view=self)

        log.tree("Text Regenerated", [
            ("Personality", self.current_personality),
            ("Result Length", len(result)),
            ("Context", f"{len(self.context)} msgs" if self.context else "None"),
            ("Arabic", self.arabic),
        ], emoji="🔄")

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.secondary, emoji="✏️", row=1)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to edit instruction and regenerate."""
        modal = EditInstructionModal(self)
        await interaction.response.send_modal(modal)


# =============================================================================
# Helper Functions
# =============================================================================

async def _fetch_context(channel: discord.abc.Messageable, owner_id: int, before_message: discord.Message = None, limit: int = 20) -> list[dict]:
    """Fetch recent messages for context, marking which are from the owner."""
    context = []
    try:
        async for msg in channel.history(limit=limit, before=before_message):
            if msg.content and not msg.author.bot:
                is_me = msg.author.id == owner_id
                context.append({
                    "author": "ME" if is_me else msg.author.display_name,
                    "content": msg.content[:500],  # Truncate long messages
                    "is_me": is_me,
                })
        # Reverse so oldest is first
        context.reverse()
    except Exception:
        pass
    return context


def _build_embed(original: str, rewritten: str, instruction: Optional[str], arabic: bool = False) -> discord.Embed:
    """Build the response embed."""
    # Use description for rewritten text (4096 char limit vs 1024 for fields)
    title = "✨ Rewritten" + (" (العربية)" if arabic else "")
    result_display = rewritten if len(rewritten) <= 4000 else rewritten[:3997] + "..."

    embed = discord.Embed(
        title=title,
        description=f"```{result_display}```",
        color=0x5865F2
    )

    # Show original in field (smaller, usually shorter)
    if original:
        original_display = original if len(original) <= 500 else original[:497] + "..."
        embed.add_field(
            name="Original",
            value=f"```{original_display}```",
            inline=False
        )

    return embed


def is_owner(user_id: int) -> bool:
    """Check if user is the bot owner."""
    return user_id == config.OWNER_ID


# =============================================================================
# Cog
# =============================================================================

class WriteCog(commands.Cog):
    """Owner-only AI writing assistant."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="write", description="✍️ AI writing assistant - rewrite, generate, respond")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        text="The text to rewrite (optional - can generate from instruction alone)",
        instruction="What to do: 'fix grammar', 'respond professionally', 'make shorter', etc.",
        context="Number of recent messages to read for context (1-100)",
        arabic="Output in Arabic instead of English"
    )
    async def write(
        self,
        interaction: discord.Interaction,
        text: Optional[str] = None,
        instruction: Optional[str] = None,
        context: Optional[app_commands.Range[int, 1, 100]] = None,
        arabic: Optional[bool] = False,
    ):
        """Rewrite text using AI with custom instruction."""
        # Owner check
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not ai_service.is_available:
            await interaction.followup.send("AI service is not available.", ephemeral=True)
            return

        # Check if this is a reply - get the referenced message content
        referenced_text = None
        if interaction.message and interaction.message.reference:
            try:
                ref_msg = await interaction.channel.fetch_message(interaction.message.reference.message_id)
                referenced_text = ref_msg.content
            except Exception:
                pass

        # Try to get referenced message from the interaction's resolved data
        # (This works when using the command as a reply)
        if not referenced_text:
            try:
                # Check if there's a resolved reference in the interaction data
                if hasattr(interaction, 'data') and interaction.data:
                    resolved = interaction.data.get('resolved', {})
                    messages = resolved.get('messages', {})
                    if messages:
                        # Get the first referenced message
                        for msg_data in messages.values():
                            referenced_text = msg_data.get('content', '')
                            break
            except Exception:
                pass

        # Determine the text to work with
        working_text = text or referenced_text

        # Fetch context if requested (context is now a number 1-100)
        context_data = None
        if context and interaction.channel:
            context_data = await _fetch_context(interaction.channel, interaction.user.id, limit=context)

        # Use provided instruction or default to fixing grammar
        final_instruction = instruction

        # If no text but have instruction, generate from scratch
        if not working_text and final_instruction:
            # Generation mode - instruction only
            log.tree("Rewrite Command (Generate)", [
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Mode", "Generate from instruction"),
                ("Context", f"{len(context_data)} messages" if context_data else "None"),
                ("Instruction", final_instruction[:50]),
            ], emoji="✍️")

            result = await ai_service.rewrite("", final_instruction, context_data, arabic)

            if not result:
                log.tree("Generate Failed", [
                    ("User", f"{interaction.user}"),
                    ("Instruction", final_instruction[:50]),
                    ("Reason", "AI service returned None"),
                ], emoji="❌")
                await interaction.followup.send("Failed to generate text.", ephemeral=True)
                return

            # Build embed for generation (use description for 4096 char limit)
            title = "✨ Generated" + (" (العربية)" if arabic else "")
            result_display = result if len(result) <= 4000 else result[:3997] + "..."
            embed = discord.Embed(
                title=title,
                description=f"```{result_display}```",
                color=0x5865F2
            )
            footer_text = f"Instruction: {final_instruction[:80]}"
            if context_data:
                footer_text += f" | Context: {len(context_data)} msgs"
            if arabic:
                footer_text += " | Arabic"
            embed.set_footer(text=footer_text)

            view = RewriteView(
                original_text="",
                rewritten_text=result,
                instruction=final_instruction,
                owner_id=interaction.user.id,
                context=context_data,
                arabic=arabic,
            )

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            log.tree("Generate Complete", [
                ("Result Length", len(result)),
                ("Context Used", f"{len(context_data)} msgs" if context_data else "None"),
                ("Arabic", arabic),
            ], emoji="✅")
            return

        # Need either text or referenced message
        if not working_text:
            await interaction.followup.send(
                "Provide text, reply to a message, or give an instruction to generate.",
                ephemeral=True
            )
            return

        log.tree("Rewrite Command", [
            ("User", f"{interaction.user} ({interaction.user.id})"),
            ("Text Length", len(working_text)),
            ("Source", "provided" if text else "reply"),
            ("Context", f"{len(context_data)} messages" if context_data else "None"),
            ("Instruction", instruction or "None"),
        ], emoji="✍️")

        result = await ai_service.rewrite(working_text, final_instruction, context_data, arabic)

        if not result:
            log.tree("Rewrite Failed", [
                ("User", f"{interaction.user}"),
                ("Text Length", len(working_text)),
                ("Instruction", final_instruction[:50] if final_instruction else "None"),
                ("Reason", "AI service returned None"),
            ], emoji="❌")
            await interaction.followup.send("Failed to rewrite text.", ephemeral=True)
            return

        # Build embed and view
        embed = _build_embed(working_text, result, final_instruction, arabic)
        footer_parts = []
        if final_instruction:
            footer_parts.append(f"Instruction: {final_instruction[:60]}")
        if context_data:
            footer_parts.append(f"Context: {len(context_data)} msgs")
        if arabic:
            footer_parts.append("Arabic")
        if footer_parts:
            embed.set_footer(text=" | ".join(footer_parts))

        view = RewriteView(
            original_text=working_text,
            rewritten_text=result,
            instruction=final_instruction,
            owner_id=interaction.user.id,
            context=context_data,
            arabic=arabic,
        )

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        log.tree("Rewrite Complete", [
            ("Original Length", len(working_text)),
            ("Result Length", len(result)),
            ("Context Used", bool(context_data)),
        ], emoji="✅")


async def setup(bot: commands.Bot):
    await bot.add_cog(WriteCog(bot))
