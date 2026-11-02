"""Load the list of items to trade from a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from bot.models import WatchItem
from bot.money import usd_to_cents


def load_watchlist(path: Path) -> list[WatchItem]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Watchlist not found: {path}. Copy watchlist.example.json to watchlist.json.") from None
    except ValueError as exc:
        raise ValueError(f"Watchlist is not valid JSON: {exc}") from None
    if not isinstance(raw, list) or not raw:
        raise ValueError("Watchlist must be a non-empty JSON list.")

    items = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Watchlist entry #{index} must be an object.")
        title = str(entry.get("title", "")).strip()
        if not title:
            raise ValueError(f"Watchlist entry #{index} has no title.")
        try:
            max_buy = usd_to_cents(entry["max_buy_usd"])
            min_sell = usd_to_cents(entry["min_sell_usd"]) if entry.get("min_sell_usd") is not None else None
        except KeyError:
            raise ValueError(f"Watchlist entry #{index} ({title}) needs max_buy_usd.") from None
        except ValueError as exc:
            raise ValueError(f"Watchlist entry #{index} ({title}): {exc}") from None
        if max_buy <= 0:
            raise ValueError(f"Watchlist entry #{index} ({title}): max_buy_usd must be positive.")
        items.append(WatchItem(title=title, max_buy_cents=max_buy, min_sell_cents=min_sell))
    return items
