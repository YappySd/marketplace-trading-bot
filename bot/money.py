"""Money helpers. Everything inside the bot is integer cents, never floats."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def usd_to_cents(value) -> int:
    """Convert a dollar amount (str, int, float or Decimal) to integer cents."""
    try:
        dollars = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a money value: {value!r}") from exc
    return int((dollars * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def api_cents(value) -> int:
    """Parse a price the API returns as a string of cents, e.g. "1234"."""
    try:
        return int(Decimal(str(value).strip()))
    except InvalidOperation as exc:
        raise ValueError(f"not a cents value: {value!r}") from exc


def format_usd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"


def cents_to_dollar_string(cents: int) -> str:
    """12345 -> "123.45" (the form some DMarket endpoints expect)."""
    return f"{cents // 100}.{cents % 100:02d}"
