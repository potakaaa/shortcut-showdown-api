# PDC Concepts

## 1) Concurrency model

The backend uses Python `asyncio` with an event-loop-driven model for socket I/O, timers, and request handling. Shared mutable game/lobby state is protected with explicit locks so concurrent coroutines do not interleave critical updates (for example, progress mutation and lifecycle transitions) in unsafe ways.

Even with `asyncio`, the Python GIL remains relevant: CPU-bound work is still serialized per interpreter process and can block responsiveness if done inline. In practice, keep match-loop operations mostly I/O-bound and short; move heavy CPU work off the hot path or into separate workers/processes when needed.

## 2) Distribution pattern

The system follows an authoritative-server pattern: server state is source-of-truth, and clients are view/input terminals. Clients send intents (join, input, ready, rematch), while the server validates and applies state transitions.

Communication is client-server (not peer-to-peer), with scoped broadcast fan-out. Events are emitted only to relevant participants (room/lobby scoped) instead of global broadcast, reducing noise and preserving room isolation boundaries.

## 3) Consistency mechanisms

Deterministic challenge generation uses seeded RNG so all participants can be synchronized on the same objective stream from one authoritative seed. Mutation endpoints and realtime actions use idempotent receipts so duplicated/retried submissions do not double-apply state changes.

A monotonic `state_version` counter is incremented on each accepted state transition. Clients can use `state_version` to ignore stale/out-of-order updates, request re-sync when gaps are detected, and maintain a consistent progression view.
