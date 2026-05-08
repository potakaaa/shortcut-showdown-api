from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.game_rooms import router as game_rooms_router
from app.api.lobbies import router as lobbies_router
from app.api.players import router as players_router
from app.api.ws import router as ws_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Shortcut Showdown API",
    description="Shortcut Showdown API",
)

# Browsers preflight with OPTIONS; without CORS, `/lobbies` returns 405
# and POST requests will not reach the endpoint.
_origins = [
    o.strip() for o in settings.cors_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lobbies_router)
app.include_router(game_rooms_router)
app.include_router(players_router)
app.include_router(ws_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "status": "success",
        "message": "Shortcut Showdown API is running.",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn_kwargs = {
        "host": settings.host,
        "port": settings.port,
        "reload": False,
    }

    # Enable WSS (WebSocket Secure) if certificates are provided
    if settings.ssl_certfile and settings.ssl_keyfile:
        uvicorn_kwargs["ssl_certfile"] = settings.ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = settings.ssl_keyfile

    uvicorn.run(
        "app.main:app",
        **uvicorn_kwargs,
    )


@app.on_event("startup")
async def _start_room_sweeper() -> None:
    """Background task: periodically ensure room state to apply timeouts.

    This ensures that rounds which expire are resolved and broadcast even
    if no client activity occurs at the exact expiry moment.
    """
    import asyncio

    from app.core.game_room_manager import game_room_manager
    from app.core.game_engine import game_engine

    async def _sweeper() -> None:
        try:
            while True:
                rooms = await game_room_manager.list_rooms()
                # Call ensure_room_state for each room to apply timeouts and broadcast
                for room in rooms:
                    try:
                        await game_engine.ensure_room_state(room.id)
                    except Exception:
                        # best-effort: ignore per-room errors so sweeper continues
                        pass
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            return

    task = asyncio.create_task(_sweeper())
    # store on app state so shutdown can cancel it if needed
    app.state._room_sweeper_task = task


@app.on_event("shutdown")
async def _stop_room_sweeper() -> None:
    task = getattr(app.state, "_room_sweeper_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except Exception:
            pass
