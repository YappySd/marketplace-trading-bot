from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Balance:
    usd_cents: int


@dataclass(frozen=True)
class MarketItem:
    title: str
    price_cents: int
    item_id: str = ""


@dataclass(frozen=True)
class Target:
    """An active buy order on the marketplace."""

    target_id: str
    title: str


@dataclass(frozen=True)
class InventoryItem:
    asset_id: str
    title: str
    in_market: bool = False


@dataclass(frozen=True)
class WatchItem:
    """One line of the watchlist: what to buy and the price limits."""

    title: str
    max_buy_cents: int
    min_sell_cents: int | None = None
