"""
TrippixnBot - Webhook Utilities
===============================

Shared webhook sending functionality.

Author: حَـــــنَّـــــا
"""

import discord
from datetime import datetime, timezone
from typing import Any, Optional

from src.core import log
from src.utils.http import http_session


async def send_webhook(
    webhook_url: str,
    title: str,
    color: int,
    fields: list[dict[str, Any]],
    user: Optional[discord.User | discord.Member] = None,
    footer_text: str = "TrippixnBot",
    description: Optional[str] = None,
) -> bool:
    """
    Send an embed to a Discord webhook.

    Args:
        webhook_url: The webhook URL to send to
        title: Embed title
        color: Embed color (hex int)
        fields: List of field dicts with name, value, inline
        user: Optional user for thumbnail
        footer_text: Footer text
        description: Optional embed description

    Returns:
        True if successful, False otherwise
    """
    if not webhook_url:
        return False

    try:
        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": footer_text},
        }

        if description:
            embed["description"] = description

        if user and user.display_avatar:
            embed["thumbnail"] = {"url": user.display_avatar.url}

        payload = {"embeds": [embed]}

        async with http_session.post(webhook_url, json=payload) as resp:
            if resp.status in (200, 204):
                return True
            else:
                log.warning(f"Webhook returned status {resp.status}")
                return False

    except Exception as e:
        log.error("Failed to send webhook", [
            ("Error", type(e).__name__),
            ("Message", str(e)),
        ])
        return False


def build_field(name: str, value: str, inline: bool = True) -> dict:
    """Helper to build a webhook field."""
    return {"name": name, "value": value, "inline": inline}


def build_code_field(name: str, value: str, inline: bool = False, max_len: int = 500) -> dict:
    """Helper to build a code block field."""
    if len(value) > max_len:
        value = value[:max_len - 3] + "..."
    return {"name": name, "value": f"```\n{value}\n```", "inline": inline}
