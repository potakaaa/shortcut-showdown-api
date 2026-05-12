"""Edge-case tests for per-room lock sharding behavior."""

from __future__ import annotations

import asyncio
import gc
import time

from app.core.game_engine import game_engine
from app.core.game_room_manager import game_room_manager
from app.models.game_room import GameRoom, GameSessionStatus


def test_get_room_lock_is_idempotent_under_concurrency() -> None:
    """Concurrent callers for the same room id should receive the same Lock object."""

    async def _run() -> None:
        room_id = "race-room"

        async def get_lock() -> object:
            return await game_engine._get_room_lock(room_id)

        results = await asyncio.gather(*(get_lock() for _ in range(12)))
        # all returned locks should be the identical object
        first = results[0]
        for r in results[1:]:
            assert r is first

    asyncio.run(_run())


def test_room_lock_entries_are_gc_cleaned() -> None:
    """Locks held only in the WeakValueDictionary should be garbage-collected."""

    async def _run() -> None:
        room_id = "transient-room"
        lock = await game_engine._get_room_lock(room_id)
        # ensure lock is present while referenced
        assert game_engine._room_locks.get(room_id) is lock
        # drop our strong reference and force GC
        del lock

    asyncio.run(_run())
    # run GC and give CPython a moment
    gc.collect()
    time.sleep(0.01)
    assert game_engine._room_locks.get("transient-room") is None


def test_per_room_state_isolation() -> None:
    """Submitting to one room should not affect another room's state_version."""

    async def _run() -> None:
        # create two minimal rooms
        r1 = GameRoom(
            id="r1",
            players=("p1",),
            game_state={
                "status": GameSessionStatus.RUNNING.value,
                "state_version": 1,
                "round_started_at": time.time(),
                "round_ends_at": time.time() + 60,
                "challenges": [{"expectedKeys": ["a"], "prompt": "A"}],
                "roster": ["p1"],
                "player_display_names": {"p1": "p1"},
                "progress": {"p1": {"objective_index": 0}},
                "rate_limit": {},
                "attempt_receipts": {},
            },
            locked=True,
        )

        r2 = GameRoom(
            id="r2",
            players=("p2",),
            game_state={
                "status": GameSessionStatus.RUNNING.value,
                "state_version": 1,
                "round_started_at": time.time(),
                "round_ends_at": time.time() + 60,
                "challenges": [{"expectedKeys": ["b"], "prompt": "B"}],
                "roster": ["p2"],
                "player_display_names": {"p2": "p2"},
                "progress": {"p2": {"objective_index": 0}},
                "rate_limit": {},
                "attempt_receipts": {},
            },
            locked=True,
        )

        await game_room_manager.register_room(r1)
        await game_room_manager.register_room(r2)

        # submit a correct attempt to r1
        await game_engine.submit_attempt(
            room_id="r1",
            player_id="p1",
            objective_index=0,
            keys=["a"],
            attempt_id="t1",
        )

        # fetch both states
        room1 = await game_room_manager.get_room("r1")
        room2 = await game_room_manager.get_room("r2")
        assert room1 is not None and room2 is not None
        # state_version for r1 should have advanced (>=2)
        assert int(room1.game_state.get("state_version", 0)) >= 2
        # r2 should remain at 1 because no activity occurred
        assert int(room2.game_state.get("state_version", 0)) == 1

    asyncio.run(_run())
