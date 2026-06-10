from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Dict
import asyncio
import json

router = APIRouter(prefix="/stream", tags=["streaming"])


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, avatar_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[avatar_id] = websocket

    def disconnect(self, avatar_id: str):
        if avatar_id in self.active_connections:
            del self.active_connections[avatar_id]

    async def send_deformation(self, avatar_id: str, data: dict):
        if avatar_id in self.active_connections:
            await self.active_connections[avatar_id].send_json(data)


manager = ConnectionManager()


@router.websocket("/{avatar_id}")
async def stream_avatar(websocket: WebSocket, avatar_id: str):
    """
    WebSocket endpoint for streaming avatar deformations

    Receives deformation updates and sends them to client
    """
    await manager.connect(avatar_id, websocket)

    try:
        while True:
            # Wait for messages (could be control messages from client)
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle different message types
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(avatar_id)


@router.post("/{avatar_id}/push")
async def push_deformation(avatar_id: str, deformation_data: dict):
    """
    Push deformation update to connected clients
    Used by worker to stream animation updates
    """
    try:
        await manager.send_deformation(avatar_id, deformation_data)
        return {"status": "sent"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
