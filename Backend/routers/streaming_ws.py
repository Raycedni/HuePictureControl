"""WebSocket /ws/status endpoint for real-time streaming metrics.

Exports:
    router -- APIRouter with /ws/status WebSocket endpoint
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["streaming"])


@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    """Stream real-time JSON metrics to connected clients.

    Connects the client to the StatusBroadcaster, which sends an initial
    metrics snapshot and then delivers updates at 1 Hz (heartbeat) and
    immediately on state transitions.

    The endpoint keeps the connection alive by receiving client messages
    (e.g. browser ping frames). On disconnect it cleanly removes the
    client from the broadcaster.
    """
    broadcaster = websocket.app.state.broadcaster
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive; client may send pings
    except (WebSocketDisconnect, Exception):
        broadcaster.disconnect(websocket)
