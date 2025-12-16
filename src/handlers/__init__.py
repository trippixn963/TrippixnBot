"""
TrippixnBot - Handlers Module
=============================

Author: حَـــــنَّـــــا
"""

from src.handlers.ready import on_ready, on_presence_update
from src.handlers.message import on_message, on_automod_action

__all__ = ["on_ready", "on_presence_update", "on_message", "on_automod_action"]
