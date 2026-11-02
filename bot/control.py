"""Telegram control panel: four buttons (start, stop, logs, status).

Only the configured chat id is obeyed. Messages from anyone else are ignored,
so a leaked bot username cannot be used to stop or start trading.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

BTN_START = "▶️ Запуск"
BTN_STOP = "⏹ Остановить"
BTN_LOGS = "📜 Логи"
BTN_STATUS = "ℹ️ Статус бота"

KEYBOARD = {
    "keyboard": [
        [{"text": BTN_START}, {"text": BTN_STOP}],
        [{"text": BTN_LOGS}, {"text": BTN_STATUS}],
    ],
    "resize_keyboard": True,
}


def tail_lines(path: Path, count: int = 15, max_chars: int = 3500) -> str:
    """Last lines of a log file, trimmed to fit in one Telegram message."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 64 * 1024))
            data = handle.read()
    except OSError:
        return "Лог-файл пока пуст."
    lines = data.decode("utf-8", errors="replace").splitlines()[-count:]
    text = "\n".join(lines).strip()
    if not text:
        return "Лог-файл пока пуст."
    return text[-max_chars:]


class ControlPanel:
    def __init__(self, notifier, runner, *, chat_id: int, log_file: Path, sleep=asyncio.sleep) -> None:
        self._notifier = notifier
        self._runner = runner
        self._chat_id = chat_id
        self._log_file = Path(log_file)
        self._sleep = sleep

    async def handle_update(self, update: dict) -> str | None:
        """Process one Telegram update. Returns the action taken (None if ignored)."""
        message = update.get("message") or {}
        if (message.get("chat") or {}).get("id") != self._chat_id:
            logger.warning("Ignored a message from an unauthorised chat")
            return None

        text = (message.get("text") or "").strip()
        if text in ("/start", "/menu"):
            await self._notifier.send("Панель управления ботом.", keyboard=KEYBOARD)
            return "menu"
        if text == BTN_START:
            started = self._runner.start()
            await self._notifier.send("Запущен." if started else "Уже работает.", keyboard=KEYBOARD)
            return "start"
        if text == BTN_STOP:
            stopped = await self._runner.stop()
            await self._notifier.send("Остановлен." if stopped else "Уже остановлен.", keyboard=KEYBOARD)
            return "stop"
        if text == BTN_LOGS:
            await self._notifier.send(tail_lines(self._log_file), keyboard=KEYBOARD)
            return "logs"
        if text == BTN_STATUS:
            await self._notifier.send(self._runner.status_text(), keyboard=KEYBOARD)
            return "status"
        await self._notifier.send("Не понял. Используй кнопки ниже.", keyboard=KEYBOARD)
        return "unknown"

    async def poll_forever(self) -> None:
        offset: int | None = None
        while True:
            try:
                updates = await self._notifier.get_updates(offset)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram polling failed: {}", exc)
                await self._sleep(5)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    await self.handle_update(update)
                except Exception as exc:
                    logger.exception("Panel handler failed: {}", exc)
