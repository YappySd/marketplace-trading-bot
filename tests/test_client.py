import asyncio
import json

import pytest

from bot.client import ApiError, DMarketClient
from bot.http import TransportError
from tests.helpers import PUBLIC_KEY, SECRET_KEY, FakeSleep, FakeTransport


def make_client(transport, *, dry_run=False, sleep=None, **kwargs):
    return DMarketClient(
        PUBLIC_KEY,
        SECRET_KEY,
        transport,
        dry_run=dry_run,
        sleep=sleep or FakeSleep(),
        min_interval=0,
        rng=lambda: 1.0,  # full ceiling, no randomness in tests
        **kwargs,
    )


def run(coro):
    return asyncio.run(coro)


def test_get_balance_signs_the_request_and_parses_cents():
    transport = FakeTransport()
    transport.queue(200, {"usd": "1234"})
    client = make_client(transport)

    balance = run(client.get_balance())

    assert balance.usd_cents == 1234
    request = transport.requests[0]
    assert request["method"] == "GET"
    assert request["url"] == "https://api.dmarket.com/account/v1/balance"
    assert {"X-Api-Key", "X-Request-Sign", "X-Sign-Date"} <= set(request["headers"])


def test_market_items_parse_and_skip_malformed_rows():
    transport = FakeTransport()
    transport.queue(
        200,
        {
            "objects": [
                {"title": "A", "price": {"USD": "150"}, "itemId": "i1"},
                {"title": "B"},  # no price: skipped
                {"title": "C", "price": {"USD": "oops"}},  # bad number: skipped
            ]
        },
    )
    items = run(make_client(transport).get_market_items("a8db", "A"))

    assert [(i.title, i.price_cents) for i in items] == [("A", 150)]
    assert "title=A" in transport.requests[0]["url"]


def test_targets_and_inventory_accept_both_key_spellings():
    transport = FakeTransport()
    transport.queue(200, {"Items": [{"TargetID": "t1", "Title": "A"}, {"targetId": "t2", "title": "B"}]})
    transport.queue(200, {"Items": [{"AssetID": "a1", "Title": "A", "InMarket": True}, {"assetId": "a2", "title": "B"}]})
    client = make_client(transport)

    targets = run(client.list_targets("a8db"))
    inventory = run(client.get_inventory("a8db"))

    assert [t.target_id for t in targets] == ["t1", "t2"]
    assert [(i.asset_id, i.in_market) for i in inventory] == [("a1", True), ("a2", False)]


def test_create_target_sends_the_expected_body():
    transport = FakeTransport()
    transport.queue(200, {"Result": []})
    run(make_client(transport).create_target("a8db", "Item ★", 150))

    request = transport.requests[0]
    body = json.loads(request["data"].decode("utf-8"))
    assert request["method"] == "POST"
    assert request["url"].endswith("/exchange/v1/target/create")
    assert body["GameID"] == "a8db"
    assert body["Targets"][0]["Price"] == {"Amount": "1.50", "Currency": "USD"}
    assert body["Targets"][0]["Title"] == "Item ★"
    assert request["headers"]["Content-Type"] == "application/json"


def test_dry_run_never_sends_writes_but_still_reads():
    transport = FakeTransport()
    transport.queue(200, {"usd": "100"})
    client = make_client(transport, dry_run=True)

    run(client.get_balance())  # reads go through
    result = run(client.create_target("a8db", "A", 100))
    run(client.create_offer("asset", 200))
    run(client.delete_target("t1"))

    assert result == {"dry_run": True}
    assert len(transport.requests) == 1  # only the balance read


def test_retries_429_and_honours_retry_after():
    transport = FakeTransport()
    transport.queue(429, {"error": "slow down"}, headers={"Retry-After": "3"})
    transport.queue(200, {"usd": "5"})
    sleep = FakeSleep()
    client = make_client(transport, sleep=sleep)

    balance = run(client.get_balance())

    assert balance.usd_cents == 5
    assert len(transport.requests) == 2
    assert 3.0 in sleep.calls


def test_retries_network_errors_with_backoff_then_gives_up():
    transport = FakeTransport()
    for _ in range(3):
        transport.queue_error(TransportError("ClientConnectionError"))
    sleep = FakeSleep()
    client = make_client(transport, sleep=sleep, max_retries=2)

    with pytest.raises(ApiError) as info:
        run(client.get_balance())

    assert info.value.status == 0
    assert len(transport.requests) == 3
    assert sleep.calls == [0.5, 1.0]  # exponential: base, base*2


def test_client_errors_are_not_retried():
    transport = FakeTransport()
    transport.queue(401, {"error": "bad signature"})
    client = make_client(transport)

    with pytest.raises(ApiError) as info:
        run(client.get_balance())

    assert info.value.status == 401
    assert len(transport.requests) == 1


def test_invalid_json_is_reported():
    transport = FakeTransport()
    transport.queue(200, "<html>oops</html>")
    with pytest.raises(ApiError):
        run(make_client(transport).get_balance())


def test_error_messages_do_not_contain_the_secret():
    transport = FakeTransport()
    transport.queue(400, {"error": "bad"})
    with pytest.raises(ApiError) as info:
        run(make_client(transport).get_balance())
    assert SECRET_KEY not in str(info.value)
