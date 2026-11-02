import json

import pytest

from bot.config import ConfigError, load_settings
from bot.strategy import buy_target_price, sell_price
from bot.watchlist import load_watchlist
from tests.helpers import PUBLIC_KEY, SECRET_KEY

# ------------------------------------------------------------------ strategy


def test_buy_price_undercuts_but_respects_the_limit():
    assert buy_target_price(200, 500) == 199  # one cent under the cheapest offer
    assert buy_target_price(900, 500) == 500  # capped by the limit
    assert buy_target_price(None, 500) is None  # nothing on the market
    assert buy_target_price(1, 500) is None  # would be a zero price
    assert buy_target_price(200, 0) is None


def test_sell_price_has_a_floor_and_needs_one():
    assert sell_price(300, 250) == 299
    assert sell_price(240, 250) == 250  # never below the floor
    assert sell_price(300, None) is None  # no floor: do not sell
    assert sell_price(None, 250) is None


# ----------------------------------------------------------------- watchlist


def write_list(tmp_path, data):
    path = tmp_path / "watchlist.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_watchlist_loads_prices_as_cents(tmp_path):
    path = write_list(tmp_path, [{"title": "A", "max_buy_usd": 1.5, "min_sell_usd": 2}, {"title": "B", "max_buy_usd": "4"}])
    items = load_watchlist(path)
    assert (items[0].max_buy_cents, items[0].min_sell_cents) == (150, 200)
    assert (items[1].max_buy_cents, items[1].min_sell_cents) == (400, None)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"title": "A"},
        [{"max_buy_usd": 1}],
        [{"title": "A"}],
        [{"title": "A", "max_buy_usd": 0}],
        [{"title": "A", "max_buy_usd": "abc"}],
    ],
)
def test_watchlist_rejects_bad_input(tmp_path, data):
    with pytest.raises(ValueError):
        load_watchlist(write_list(tmp_path, data))


def test_watchlist_missing_file_gives_a_helpful_message(tmp_path):
    with pytest.raises(ValueError, match="watchlist.example.json"):
        load_watchlist(tmp_path / "nope.json")


# -------------------------------------------------------------------- config

BASE_ENV = {"DMARKET_PUBLIC_KEY": PUBLIC_KEY, "DMARKET_SECRET_KEY": SECRET_KEY}


def test_defaults_are_safe():
    settings = load_settings(BASE_ENV)
    assert settings.dry_run is True
    assert settings.telegram_enabled is False
    assert settings.scan_interval == 60


def test_dry_run_can_be_switched_off_explicitly():
    assert load_settings({**BASE_ENV, "DRY_RUN": "0"}).dry_run is False
    assert load_settings({**BASE_ENV, "DRY_RUN": "false"}).dry_run is False
    assert load_settings({**BASE_ENV, "DRY_RUN": "1"}).dry_run is True


def test_secrets_never_appear_in_repr():
    settings = load_settings({**BASE_ENV, "TELEGRAM_BOT_TOKEN": "123456:SECRET-TOKEN", "TELEGRAM_CHAT_ID": "42"})
    text = repr(settings)
    assert SECRET_KEY not in text
    assert "SECRET-TOKEN" not in text


@pytest.mark.parametrize(
    "extra",
    [
        {"DMARKET_PUBLIC_KEY": ""},
        {"DMARKET_SECRET_KEY": "not-hex"},
        {"TELEGRAM_BOT_TOKEN": "x"},  # chat id missing
        {"TELEGRAM_CHAT_ID": "42"},  # token missing
        {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "abc"},
        {"SCAN_INTERVAL_SEC": "1"},
        {"SCAN_INTERVAL_SEC": "fast"},
    ],
)
def test_bad_configuration_is_rejected(extra):
    with pytest.raises(ConfigError):
        load_settings({**BASE_ENV, **extra})
