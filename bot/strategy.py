"""Pricing rules.

This is intentionally a simple, public stub: it shows where a real strategy
plugs in (two pure functions, easy to test), but it is not the logic the
production bot uses. Replace these functions with your own rules.
"""

from __future__ import annotations

UNDERCUT_CENTS = 1


def buy_target_price(lowest_offer_cents: int | None, max_buy_cents: int) -> int | None:
    """Price for a buy order, or None to skip.

    Rule: bid one cent under the cheapest current offer, but never above the
    configured limit.
    """
    if lowest_offer_cents is None or max_buy_cents <= 0:
        return None
    price = min(max_buy_cents, lowest_offer_cents - UNDERCUT_CENTS)
    return price if price > 0 else None


def sell_price(lowest_offer_cents: int | None, floor_cents: int | None) -> int | None:
    """Price to list an item at, or None to keep it.

    Rule: undercut the cheapest offer by one cent, but never go below the floor.
    No floor configured means the bot will not sell that item.
    """
    if lowest_offer_cents is None or floor_cents is None:
        return None
    return max(floor_cents, lowest_offer_cents - UNDERCUT_CENTS)
