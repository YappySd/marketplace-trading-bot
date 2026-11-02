"""Start/stop the trader task and describe its state (used by the Telegram panel)."""

from __future__ import annotations

import asyncio
import time

from bot.money import format_usd


class TraderRunner:
    def __init__(self, trader, *, dry_run: bool, stop_timeout: float = 30.0) -> None:
        self._trader = trader
        self._dry_run = dry_run
        self._stop_timeout = stop_timeout
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> bool:
        if self.is_running:
            return False
        self._task = asyncio.create_task(self._trader.run_forever())
        return True

    async def stop(self) -> bool:
        if not self.is_running:
            return False
        self._trader.request_stop()
        try:
            await asyncio.wait_for(self._task, timeout=self._stop_timeout)
        except asyncio.TimeoutError:
            self._task.cancel()
        return True

    def status_text(self) -> str:
        mode = "DRY-RUN (без реальных сделок)" if self._dry_run else "БОЕВОЙ режим"
        state = "работает" if self.is_running else "остановлен"
        lines = [f"Статус: {state}", f"Режим: {mode}", f"Циклов выполнено: {self._trader.cycles}"]
        report = self._trader.last_report
        if report is not None:
            ago = int(time.time() - report.started_at)
            lines += [
                f"Последний цикл: {ago} с назад",
                f"Баланс: {format_usd(report.balance_cents)}",
                f"Целей создано: {report.targets_created}",
                f"Выставлено на продажу: {report.offers_created}",
                f"Ошибок: {report.errors}",
            ]
        return "\n".join(lines)
