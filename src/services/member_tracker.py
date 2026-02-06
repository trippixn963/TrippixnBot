"""
TrippixnBot - Member Tracker
============================

Tracks current member count.

Author: حَـــــنَّـــــا
"""

from src.core import log


# =============================================================================
# Member Tracker
# =============================================================================

class MemberTracker:
    """Tracks current member count."""

    def __init__(self):
        self._count: int = 0
        self._online_count: int = 0

    def update(self, member_count: int, online_count: int = 0) -> None:
        """Update member counts."""
        self._count = member_count
        self._online_count = online_count

    def get_count(self) -> int:
        """Get current member count."""
        return self._count

    def get_online_count(self) -> int:
        """Get current online count."""
        return self._online_count


# Global instance
member_tracker = MemberTracker()
