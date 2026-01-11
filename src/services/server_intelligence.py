"""
TrippixnBot - Server Intelligence Service
==========================================

Builds comprehensive understanding of the server:
- Channels, roles, categories
- Message patterns and recent conversations
- User profiles and behavior

Author: حَـــــنَّـــــا
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
import discord

from src.core import config, log


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class UserProfile:
    """Tracked information about a user."""
    user_id: int
    username: str
    display_name: str
    roles: list[str] = field(default_factory=list)
    message_count: int = 0
    last_seen: float = 0
    active_channels: dict[str, int] = field(default_factory=dict)  # channel_name: message_count
    recent_messages: list[str] = field(default_factory=list)  # Last few messages
    topics: list[str] = field(default_factory=list)  # Detected interests/topics

    def add_message(self, channel_name: str, content: str):
        """Record a message from this user."""
        self.message_count += 1
        self.last_seen = time.time()
        self.active_channels[channel_name] = self.active_channels.get(channel_name, 0) + 1

        # Keep last 10 messages for context
        if content and len(content) > 5:
            self.recent_messages.append(content[:200])
            if len(self.recent_messages) > 10:
                self.recent_messages.pop(0)


@dataclass
class ChannelContext:
    """Context about a channel."""
    name: str
    id: int
    category: str
    topic: str
    recent_messages: list[dict] = field(default_factory=list)  # [{author, content, timestamp}]
    active_users: set[int] = field(default_factory=set)
    message_count: int = 0


# =============================================================================
# Server Intelligence Service
# =============================================================================

class ServerIntelligence:
    """
    Builds and maintains comprehensive server knowledge.

    This service:
    - Scans server structure (channels, roles, categories)
    - Monitors messages to understand conversations
    - Builds user profiles based on behavior
    - Provides context for AI responses
    """

    MAX_RECENT_MESSAGES = 50  # Per channel
    MAX_USER_PROFILES = 500   # Limit memory usage
    CONTEXT_WINDOW = 3600     # 1 hour - messages older than this are less relevant

    def __init__(self):
        self.bot: Optional[discord.Client] = None
        self.guild: Optional[discord.Guild] = None

        # Server structure
        self.roles: dict[int, dict] = {}  # role_id: {name, color, position, member_count}
        self.channels: dict[int, ChannelContext] = {}  # channel_id: ChannelContext
        self.categories: dict[str, list[str]] = {}  # category_name: [channel_names]

        # User tracking
        self.user_profiles: dict[int, UserProfile] = {}  # user_id: UserProfile

        # Owner info
        self.owner_profile: Optional[UserProfile] = None
        self.owner_recent_activity: list[dict] = []  # Recent owner messages for style

        # Server stats
        self.total_members: int = 0
        self.online_members: int = 0
        self.boost_level: int = 0
        self.boost_count: int = 0

        self._initialized = False

    async def setup(self, bot: discord.Client, guild_id: int) -> None:
        """Initialize the service with bot and guild."""
        self.bot = bot
        self.guild = bot.get_guild(guild_id)

        if not self.guild:
            log.tree("Server Intelligence Setup Failed", [
                ("Reason", "Guild not found"),
                ("Guild ID", str(guild_id)),
            ], emoji="❌")
            return

        log.tree("Server Intelligence Setup", [
            ("Guild", self.guild.name),
            ("Guild ID", str(guild_id)),
            ("Status", "Scanning..."),
        ], emoji="🧠")

        # Scan server structure
        await self._scan_roles()
        await self._scan_channels()
        await self._scan_members()

        self._initialized = True

        log.tree("Server Intelligence Ready", [
            ("Guild", self.guild.name),
            ("Roles", str(len(self.roles))),
            ("Channels", str(len(self.channels))),
            ("Categories", str(len(self.categories))),
            ("Members Tracked", str(len(self.user_profiles))),
        ], emoji="✅")

    async def _scan_roles(self) -> None:
        """Scan all server roles."""
        if not self.guild:
            return

        for role in self.guild.roles:
            if role.name == "@everyone":
                continue

            self.roles[role.id] = {
                "name": role.name,
                "color": str(role.color),
                "position": role.position,
                "member_count": len(role.members),
                "permissions": self._summarize_permissions(role.permissions),
                "mentionable": role.mentionable,
            }

        log.tree("Roles Scanned", [
            ("Total", str(len(self.roles))),
            ("Top Roles", ", ".join([r["name"] for r in sorted(self.roles.values(), key=lambda x: x["position"], reverse=True)[:5]])),
        ], emoji="🏷️")

    def _summarize_permissions(self, perms: discord.Permissions) -> list[str]:
        """Get notable permissions for a role."""
        notable = []
        if perms.administrator:
            notable.append("Admin")
        if perms.manage_guild:
            notable.append("Manage Server")
        if perms.manage_channels:
            notable.append("Manage Channels")
        if perms.manage_roles:
            notable.append("Manage Roles")
        if perms.manage_messages:
            notable.append("Manage Messages")
        if perms.kick_members:
            notable.append("Kick")
        if perms.ban_members:
            notable.append("Ban")
        if perms.moderate_members:
            notable.append("Timeout")
        return notable

    async def _scan_channels(self) -> None:
        """Scan all server channels."""
        if not self.guild:
            return

        for channel in self.guild.channels:
            if isinstance(channel, discord.TextChannel):
                category_name = channel.category.name if channel.category else "No Category"

                self.channels[channel.id] = ChannelContext(
                    name=channel.name,
                    id=channel.id,
                    category=category_name,
                    topic=channel.topic or "",
                )

                # Track by category
                if category_name not in self.categories:
                    self.categories[category_name] = []
                self.categories[category_name].append(channel.name)

        log.tree("Channels Scanned", [
            ("Total", str(len(self.channels))),
            ("Categories", str(len(self.categories))),
        ], emoji="📂")

    async def _scan_members(self) -> None:
        """Scan server members and create initial profiles."""
        if not self.guild:
            return

        self.total_members = self.guild.member_count or 0
        self.online_members = sum(1 for m in self.guild.members if m.status != discord.Status.offline)
        self.boost_level = self.guild.premium_tier
        self.boost_count = self.guild.premium_subscription_count or 0

        # Track owner specifically
        if self.guild.owner:
            self.owner_profile = UserProfile(
                user_id=self.guild.owner.id,
                username=self.guild.owner.name,
                display_name=self.guild.owner.display_name,
                roles=[r.name for r in self.guild.owner.roles if r.name != "@everyone"],
            )

        # Track active/notable members (those with roles or recent activity)
        for member in self.guild.members:
            if member.bot:
                continue

            # Only pre-track members with notable roles
            if len(member.roles) > 1:  # More than just @everyone
                self._get_or_create_profile(member)

        log.tree("Members Scanned", [
            ("Total", str(self.total_members)),
            ("Online", str(self.online_members)),
            ("Boost Level", str(self.boost_level)),
            ("Boosters", str(self.boost_count)),
            ("Profiles Created", str(len(self.user_profiles))),
        ], emoji="👥")

    def _get_or_create_profile(self, member: discord.Member) -> UserProfile:
        """Get or create a user profile."""
        if member.id not in self.user_profiles:
            # Limit total profiles to prevent memory bloat
            if len(self.user_profiles) >= self.MAX_USER_PROFILES:
                # Remove oldest profile
                oldest_id = min(self.user_profiles.keys(), key=lambda x: self.user_profiles[x].last_seen)
                del self.user_profiles[oldest_id]

            self.user_profiles[member.id] = UserProfile(
                user_id=member.id,
                username=member.name,
                display_name=member.display_name,
                roles=[r.name for r in member.roles if r.name != "@everyone"],
            )

        return self.user_profiles[member.id]

    def record_message(self, message: discord.Message) -> None:
        """Record a message for context building."""
        if not self._initialized or not message.guild:
            return

        if message.author.bot:
            return

        channel_id = message.channel.id
        user_id = message.author.id
        content = message.content[:500] if message.content else ""

        # Update channel context
        if channel_id in self.channels:
            ctx = self.channels[channel_id]
            ctx.message_count += 1
            ctx.active_users.add(user_id)

            # Keep recent messages
            ctx.recent_messages.append({
                "author": message.author.display_name,
                "author_id": user_id,
                "content": content,
                "timestamp": time.time(),
            })

            # Trim old messages
            if len(ctx.recent_messages) > self.MAX_RECENT_MESSAGES:
                ctx.recent_messages = ctx.recent_messages[-self.MAX_RECENT_MESSAGES:]

        # Update user profile
        if isinstance(message.author, discord.Member):
            profile = self._get_or_create_profile(message.author)
            channel_name = message.channel.name if hasattr(message.channel, 'name') else "DM"
            profile.add_message(channel_name, content)

            # Track owner activity specifically
            if user_id == config.OWNER_ID:
                self.owner_recent_activity.append({
                    "channel": channel_name,
                    "content": content,
                    "timestamp": time.time(),
                })
                # Keep last 20 owner messages
                if len(self.owner_recent_activity) > 20:
                    self.owner_recent_activity.pop(0)

    def get_server_context(self) -> str:
        """Get comprehensive server context for AI."""
        if not self._initialized or not self.guild:
            return "Server context not available."

        lines = []

        # Server overview
        lines.append(f"=== SERVER: {self.guild.name} ===")
        lines.append(f"Members: {self.total_members} | Online: {self.online_members}")
        lines.append(f"Boost Level: {self.boost_level} ({self.boost_count} boosters)")
        if self.guild.owner:
            lines.append(f"Owner: {self.guild.owner.display_name}")
        lines.append("")

        # Staff members (admins and mods)
        lines.append("=== STAFF ===")
        staff_found = []
        for role_id, role_info in self.roles.items():
            if any(p in role_info["permissions"] for p in ["Admin", "Manage Server", "Manage Messages", "Ban", "Kick"]):
                role = self.guild.get_role(role_id)
                if role and role.members:
                    for member in role.members[:5]:  # Max 5 per role
                        if member.id not in [s[0] for s in staff_found]:
                            staff_found.append((member.id, member.display_name, role_info["name"]))
        for _, name, role in staff_found[:15]:  # Max 15 staff
            lines.append(f"  {name} (@{role})")
        lines.append("")

        # Categories and channels (with IDs for proper Discord mentions)
        lines.append("=== CHANNELS (use <#id> format to mention) ===")
        for category, channels in sorted(self.categories.items()):
            lines.append(f"[{category}]")
            for ch_name in channels[:10]:  # Limit per category
                # Find channel context
                ch_ctx = next((c for c in self.channels.values() if c.name == ch_name), None)
                if ch_ctx:
                    if ch_ctx.topic:
                        lines.append(f"  <#{ch_ctx.id}> ({ch_name}) - {ch_ctx.topic[:50]}")
                    else:
                        lines.append(f"  <#{ch_ctx.id}> ({ch_name})")
        lines.append("")

        # Notable roles
        lines.append("=== ROLES ===")
        sorted_roles = sorted(self.roles.values(), key=lambda x: x["position"], reverse=True)
        for role in sorted_roles[:15]:  # Top 15 roles
            perms = ", ".join(role["permissions"][:3]) if role["permissions"] else "Basic"
            lines.append(f"@{role['name']} ({role['member_count']} members) - {perms}")
        lines.append("")

        # Bots in the server
        lines.append("=== BOTS ===")
        bots = [m for m in self.guild.members if m.bot][:10]
        for bot in bots:
            lines.append(f"  {bot.display_name}")
        lines.append("")

        return "\n".join(lines)

    def get_channel_context(self, channel_id: int, limit: int = 10) -> str:
        """Get recent context for a specific channel."""
        if channel_id not in self.channels:
            return ""

        ctx = self.channels[channel_id]
        if not ctx.recent_messages:
            return f"Channel #{ctx.name} - No recent messages."

        lines = [f"=== Recent in #{ctx.name} ==="]

        # Get recent messages within time window
        now = time.time()
        recent = [m for m in ctx.recent_messages if now - m["timestamp"] < self.CONTEXT_WINDOW]

        for msg in recent[-limit:]:
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            lines.append(f"{msg['author']}: {content}")

        return "\n".join(lines)

    def get_user_context(self, user_id: int) -> str:
        """Get context about a specific user."""
        if user_id not in self.user_profiles:
            return "Unknown user."

        profile = self.user_profiles[user_id]

        lines = [f"=== User: {profile.display_name} ==="]
        lines.append(f"Roles: {', '.join(profile.roles[:5])}")
        lines.append(f"Messages: {profile.message_count}")

        if profile.active_channels:
            top_channels = sorted(profile.active_channels.items(), key=lambda x: x[1], reverse=True)[:3]
            lines.append(f"Active in: {', '.join([f'#{ch}' for ch, _ in top_channels])}")

        if profile.recent_messages:
            lines.append("Recent messages:")
            for msg in profile.recent_messages[-3:]:
                lines.append(f"  \"{msg[:80]}...\"" if len(msg) > 80 else f"  \"{msg}\"")

        return "\n".join(lines)

    def get_owner_style_context(self) -> str:
        """Get context about how the owner typically writes."""
        if not self.owner_recent_activity:
            return ""

        lines = ["=== OWNER'S WRITING STYLE (mimic this) ==="]
        for activity in self.owner_recent_activity[-5:]:
            if activity["content"]:
                lines.append(f"Example: \"{activity['content'][:150]}\"")

        return "\n".join(lines)

    def build_ai_context(self, channel_id: int = None, user_id: int = None) -> str:
        """Build comprehensive context for AI response."""
        parts = []

        # Always include server overview
        parts.append(self.get_server_context())

        # Include channel context if specified
        if channel_id:
            channel_ctx = self.get_channel_context(channel_id)
            if channel_ctx:
                parts.append(channel_ctx)

        # Include user context if specified
        if user_id:
            user_ctx = self.get_user_context(user_id)
            if user_ctx:
                parts.append(user_ctx)

        # Include owner style for mimicking
        owner_style = self.get_owner_style_context()
        if owner_style:
            parts.append(owner_style)

        return "\n\n".join(parts)


# Global instance
server_intel = ServerIntelligence()
