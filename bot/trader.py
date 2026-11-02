"""The trading loop: scan the watchlist, place buy targets, list owned items."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from loguru import logger

from bot import strategy
from bot.client import ApiError
from bot.models import WatchItem
from bot.money import format_usd


@dataclass
class CycleReport:
    started_at: float = field(default_factory=time.time)
    balance_cents: int = 0
    targets_created: int = 0
    offers_created: int = 0
    errors: int = 0


class Trader:
    def __init__(
        self,
        client,
        notifier,
        watchlist: list[WatchItem],
        *,
        game_id: str,
        interval: float,
        heartbeat,
    ) -> None:
        self._client = client
        self._notifier = notifier
        self._watchlist = watchlist
        self._game_id = game_id
        self._interval = interval
        self._heartbeat = heartbeat
        self._stop = asyncio.Event()
        self.cycles = 0
        self.last_report: CycleReport | None = None

    @property
    def _prefix(self) -> str:
        return "[DRY-RUN] " if getattr(self._client, "dry_run", False) else ""

    async def run_once(self) -> CycleReport:
        report = CycleReport()
        balance = await self._client.get_balance()
        report.balance_cents = balance.usd_cents
        available = balance.usd_cents

        active_titles = {t.title for t in await self._client.list_targets(self._game_id)}
        inventory = await self._client.get_inventory(self._game_id)
        listed_assets: set[str] = set()

        for item in self._watchlist:
            try:
                offers = await self._client.get_market_items(self._game_id, item.title, limit=5)
                lowest = min((o.price_cents for o in offers if o.title == item.title), default=None)

                if item.title not in active_titles:
                    price = strategy.buy_target_price(lowest, item.max_buy_cents)
                    if price is not None and price <= available:
                        await self._client.create_target(self._game_id, item.title, price)
                        available -= price
                        active_titles.add(item.title)
                        report.targets_created += 1
                        logger.info("Target: {} at {}", item.title, format_usd(price))
                        await self._notifier.send(f"{self._prefix}🎯 Цель: {item.title} по {format_usd(price)}")

                sell_at = strategy.sell_price(lowest, item.min_sell_cents)
                if sell_at is not None:
                    for owned in inventory:
                        if owned.title == item.title and not owned.in_market and owned.asset_id not in listed_assets:
                            await self._client.create_offer(owned.asset_id, sell_at)
                            listed_assets.add(owned.asset_id)
                            report.offers_created += 1
                            logger.info("Offer: {} at {}", item.title, format_usd(sell_at))
                            await self._notifier.send(
                                f"{self._prefix}🏷 Выставлено: {item.title} за {format_usd(sell_at)}"
                            )
            except ApiError as exc:
                # One bad item must not stop the rest of the watchlist.
                report.errors += 1
                logger.warning("Skipped {}: {}", item.title, exc)

        self.cycles += 1
        self.last_report = report
        self._heartbeat.beat()
        return report

    def request_stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        self._stop.clear()
        logger.info("Trader started ({} items, every {}s)", len(self._watchlist), self._interval)
        self._heartbeat.beat()
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # keep the loop alive; the watchdog covers real hangs
                logger.exception("Cycle failed: {}", exc)
                await self._notifier.send(f"⚠️ Ошибка цикла: {type(exc).__name__}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
        logger.info("Trader stopped")
