"""WebSocket handler — state management and client communication."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("live.ws_handler")


@dataclass
class LiveState:
    """Current live controller state, broadcast to all clients."""
    # Current song
    current_song_id: str | None = None
    current_song_name: str = ""
    current_artist: str = ""
    current_bpm: int = 0
    # Current chaser / step
    chaser_id: int | None = None
    current_step: int = 0
    total_steps: int = 0
    current_part_name: str = ""
    current_function_name: str = ""
    # Status
    qlc_connected: bool = False
    db_synced: bool = False
    db_sync_time: str | None = None
    db_sync_method: str = ""
    # Playback
    is_playing: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class WsHandler:
    """Manages WebSocket connections and live state."""

    def __init__(self):
        self.state = LiveState()
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        """Accept a new WebSocket client and send initial state."""
        await ws.accept()
        self._clients.add(ws)
        log.info("WS client connected (%d total)", len(self._clients))
        # Send full state on connect
        await self._send(ws, {"type": "state", "data": self.state.to_dict()})

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a disconnected client."""
        self._clients.discard(ws)
        log.info("WS client disconnected (%d remaining)", len(self._clients))

    async def _send(self, ws: WebSocket, msg: dict) -> None:
        """Send JSON message to a single client."""
        try:
            await ws.send_json(msg)
        except Exception:
            self._clients.discard(ws)

    async def broadcast(self, msg: dict) -> None:
        """Send JSON message to all connected clients."""
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_state(self) -> None:
        """Broadcast the current state to all clients."""
        await self.broadcast({"type": "state", "data": self.state.to_dict()})

    async def update_state(self, **kwargs: Any) -> None:
        """Update state fields and broadcast."""
        changed = False
        for key, value in kwargs.items():
            if hasattr(self.state, key) and getattr(self.state, key) != value:
                setattr(self.state, key, value)
                changed = True
        if changed:
            await self.broadcast_state()

    async def handle_message(self, ws: WebSocket, raw: str, action_handler) -> None:
        """Process an incoming WS message from a client.

        Expected format: {"action": "...", ...params}
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send(ws, {"type": "error", "message": "Invalid JSON"})
            return

        action = msg.get("action")
        if not action:
            await self._send(ws, {"type": "error", "message": "Missing 'action'"})
            return

        log.info("WS command: %s %s", action, {k: v for k, v in msg.items() if k != "action"})

        try:
            result = await action_handler(action, msg)
            if result:
                await self._send(ws, {"type": "result", "action": action, "data": result})
        except Exception as exc:
            log.exception("Error handling WS action '%s'", action)
            await self._send(ws, {"type": "error", "action": action, "message": str(exc)})

    @property
    def client_count(self) -> int:
        return len(self._clients)
