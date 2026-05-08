"""In-memory game room registry; gameplay is isolated per room."""

from __future__ import annotations

import asyncio
import time

from app.core.config import get_settings
from app.core.connection_manager import connection_manager
from app.models.game_room import GameRoom
from app.models.player import PlayerStatus


class GameRoomManager:
    """Tracks active game rooms and keeps player fields in sync on disconnect."""

    def __init__(self) -> None:
        self._rooms: dict[str, GameRoom] = {}
        self._expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def register_room(self, room: GameRoom) -> None:
        """Insert a room (caller must not duplicate an existing id)."""
        async with self._lock:
            self._rooms[room.id] = room
            self._expiry.pop(room.id, None)

    async def get_room(self, room_id: str) -> GameRoom | None:
        """Return a game room by id, or None if missing."""
        async with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            expires_at = self._expiry.get(room_id)
            if expires_at is not None and time.time() >= expires_at:
                self._rooms.pop(room_id, None)
                self._expiry.pop(room_id, None)
                return None
            if room.players:
                self._expiry.pop(room_id, None)
            return room

    async def list_rooms(self) -> list[GameRoom]:
        """Return a snapshot list of active rooms."""
        async with self._lock:
            return list(self._rooms.values())

    async def remove_player_from_all_rooms(self, player_id: str) -> None:
        """Remove the player from any game room (disconnect). Deletes empty rooms."""
        removed_from: str | None = None
        keepalive_seconds = max(0, int(get_settings().game_room_keepalive_seconds))

        async with self._lock:
            for rid, room in list(self._rooms.items()):
                if player_id not in room.players:
                    continue
                removed_from = rid
                new_players = tuple(p for p in room.players if p != player_id)
                if not new_players:
                    if keepalive_seconds > 0:
                        self._rooms[rid] = GameRoom(
                            id=room.id,
                            players=new_players,
                            game_state=dict(room.game_state),
                            locked=room.locked,
                        )
                        self._expiry[rid] = time.time() + keepalive_seconds
                    else:
                        del self._rooms[rid]
                        self._expiry.pop(rid, None)
                else:
                    self._rooms[rid] = GameRoom(
                        id=room.id,
                        players=new_players,
                        game_state=dict(room.game_state),
                        locked=room.locked,
                    )
                    self._expiry.pop(rid, None)
                break

        if removed_from is None:
            return

        await connection_manager.clear_subscription(player_id, "room")

        from app.core.game_engine import game_engine

        await game_engine.resolve_forfeit(removed_from, player_id)

        player = await connection_manager.get_player(player_id)
        if player is None:
            return
        if player.current_room == removed_from:
            await connection_manager.update_player(
                player_id,
                status=PlayerStatus.IDLE,
                current_room=None,
            )

    async def reset(self) -> None:
        """Clear all game rooms (used by tests)."""
        async with self._lock:
            self._rooms.clear()


game_room_manager = GameRoomManager()
