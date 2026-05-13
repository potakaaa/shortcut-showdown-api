from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings loaded from environment and optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = 8000
    host: str = "127.0.0.1"
    environment: str = "development"
    lobby_max_players: int = 2
    challenge_count: int = 10
    round_duration_seconds: int = 90
    max_attempts_per_second: int = 8
    # If a player fails this many times on the same objective, advance (skip) it.
    skip_after_failures: int = 3
    # Keep empty game rooms alive for refresh resistance (seconds).
    # Tests expect immediate removal on disconnect, so default to 0.
    game_room_keepalive_seconds: int = 0
    # Comma-separated; required for browser clients (e.g. Next.js) on another origin
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # SSL/TLS certificate paths for WSS (WebSocket Secure)
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
