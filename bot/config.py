"""Settings come from environment variables (a local `.env` file in development)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

FALSE_WORDS = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Raised with a human-readable message when the configuration is unusable."""


@dataclass(frozen=True)
class Settings:
    public_key: str
    # repr=False keeps secrets out of logs and tracebacks.
    secret_key: str = field(repr=False)
    telegram_token: str | None = field(default=None, repr=False)
    telegram_chat_id: int | None = None
    dry_run: bool = True
    game_id: str = "a8db"
    scan_interval: float = 60.0
    watchlist_path: Path = Path("watchlist.json")
    log_file: Path = Path("logs/bot.log")
    heartbeat_file: Path = Path("state/heartbeat.txt")
    base_url: str = "https://api.dmarket.com"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


def _flag(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in FALSE_WORDS


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"Fill in {name} in your .env file.")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        from dotenv import load_dotenv

        load_dotenv()
        env = os.environ

    public_key = _required(env, "DMARKET_PUBLIC_KEY")
    secret_key = _required(env, "DMARKET_SECRET_KEY")
    try:
        if len(bytes.fromhex(secret_key)) < 32:
            raise ValueError
    except ValueError:
        raise ConfigError("DMARKET_SECRET_KEY must be a hex string (at least 64 hex characters).") from None

    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip() or None
    chat_raw = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    chat_id = None
    if chat_raw:
        try:
            chat_id = int(chat_raw)
        except ValueError:
            raise ConfigError("TELEGRAM_CHAT_ID must be a number.") from None
    if bool(token) != bool(chat_id):
        raise ConfigError("Set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or neither.")

    try:
        interval = float(env.get("SCAN_INTERVAL_SEC") or 60)
    except ValueError:
        raise ConfigError("SCAN_INTERVAL_SEC must be a number.") from None
    if interval < 5:
        raise ConfigError("SCAN_INTERVAL_SEC must be at least 5 seconds.")

    return Settings(
        public_key=public_key,
        secret_key=secret_key,
        telegram_token=token,
        telegram_chat_id=chat_id,
        dry_run=_flag(env.get("DRY_RUN"), True),
        game_id=(env.get("GAME_ID") or "a8db").strip(),
        scan_interval=interval,
        watchlist_path=Path(env.get("WATCHLIST_PATH") or "watchlist.json"),
        log_file=Path(env.get("LOG_FILE") or "logs/bot.log"),
        heartbeat_file=Path(env.get("HEARTBEAT_FILE") or "state/heartbeat.txt"),
    )
