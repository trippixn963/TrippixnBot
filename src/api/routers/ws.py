"""
TrippixnBot - WebSocket Router
==============================

Real-time stats via WebSocket.

Author: حَـــــنَّـــــا
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.services.websocket import get_ws_manager
from src.api.services.stats_store import get_stats_store


router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/stats")
async def stats_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time stats updates.

    Sends current stats on connect, then broadcasts updates.
    """
    ws_manager = get_ws_manager()
    stats_store = get_stats_store()

    await ws_manager.connect(websocket)

    try:
        # Send current stats immediately on connect
        current_stats = await stats_store.get()
        await websocket.send_json({
            "type": "stats",
            "data": current_stats,
        })

        # Keep connection alive and wait for disconnect
        while True:
            # Wait for any message (ping/pong or close)
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)


__all__ = ["router"]
