"""Telegram Bot API over plain HTTPS: notifications and long-polling for the panel."""

from __future__ import annotations

import json

from loguru import logger

API_ROOT = "https://api.telegram.org"


class TelegramError(Exception):
    pass


class TelegramNotifier:
    def __init__(self, token: str | None, chat_id: int | None, transport) -> None:
        self._token = token
        self._chat_id = chat_id
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def _call(self, method: str, payload: dict, timeout: float = 15.0) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            response = await self._transport.request(
                "POST",
                f"{API_ROOT}/bot{self._token}/{method}",
                headers={"Content-Type": "application/json"},
                data=body,
                timeout=timeout,
            )
        except OSError as exc:
            # Never include the exception text: it can contain the URL (and the token).
            raise TelegramError(f"network error: {type(exc).__name__}") from None
        try:
            data = json.loads(response.text)
        except ValueError:
            raise TelegramError(f"HTTP {response.status}: invalid response") from None
        if response.status != 200 or not data.get("ok"):
            raise TelegramError(f"HTTP {response.status}: {data.get('description', 'unknown error')}")
        return data

    async def send(self, text: str, keyboard: dict | None = None) -> bool:
        """Send a message to the owner. Never raises: alerts must not crash trading."""
        if not self.enabled:
            return False
        payload = {"chat_id": self._chat_id, "text": text[:4000]}
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        try:
            await self._call("sendMessage", payload)
            return True
        except TelegramError as exc:
            logger.warning("Telegram send failed: {}", exc)
            return False

    async def get_updates(self, offset: int | None, poll_seconds: int = 30) -> list[dict]:
        """Long-poll for new messages. Raises TelegramError so the caller can back off."""
        payload: dict = {"timeout": poll_seconds, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        data = await self._call("getUpdates", payload, timeout=poll_seconds + 10)
        result = data.get("result")
        return result if isinstance(result, list) else []
