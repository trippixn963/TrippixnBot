"""
TrippixnBot - WebSocket Manager
===============================

Real-time stats broadcasting via WebSocket.

Author: حَـــــنَّـــــا
"""

import asyncio
import json
from typing import Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from src.core import log


class WebSocketManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track a new connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        log.debug("WebSocket Connected", [("Total", str(len(self._connections)))])

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection."""
        async with self._lock:
            self._connections.discard(websocket)
        log.debug("WebSocket Disconnected", [("Total", str(len(self._connections)))])

    async def broadcast(self, data: dict) -> None:
        """Broadcast data to all connected clients."""
        if not self._connections:
            return

        message = json.dumps(data)
        dead_connections = set()

        async with self._lock:
            for websocket in self._connections:
                try:
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_text(message)
                except Exception:
                    dead_connections.add(websocket)

            # Clean up dead connections
            self._connections -= dead_connections

        if dead_connections:
            log.debug("WebSocket Cleanup", [("Removed", str(len(dead_connections)))])

    @property
    def connection_count(self) -> int:
        """Get current connection count."""
        return len(self._connections)


# Singleton
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    """Get WebSocket manager singleton."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


__all__ = ["WebSocketManager", "get_ws_manager"]
