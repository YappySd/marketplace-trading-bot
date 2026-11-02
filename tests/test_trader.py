import asyncio

from bot.client import ApiError
from bot.models import Balance, InventoryItem, MarketItem, Target, WatchItem
from bot.trader import Trader


class FakeClient:
    dry_run = False

    def __init__(self, balance=10_000, offers=None, targets=(), inventory=()):
        self.balance = balance
        self.offers = offers or {}
        self.targets = list(targets)
        self.inventory = list(inventory)
        self.created_targets = []
        self.created_offers = []
        self.failing_titles = set()

    async def get_balance(self):
        return Balance(self.balance)

    async def list_targets(self, game_id):
        return self.targets

    async def get_inventory(self, game_id):
        return self.inventory

    async def get_market_items(self, game_id, title, limit=10):
        if title in self.failing_titles:
            raise ApiError(500, "boom")
        return [MarketItem(title, price) for price in self.offers.get(title, [])]

    async def create_target(self, game_id, title, price_cents, amount=1):
        self.created_targets.append((title, price_cents))
        return {}

    async def create_offer(self, asset_id, price_cents):
        self.created_offers.append((asset_id, price_cents))
        return {}


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, text, keyboard=None):
        self.messages.append(text)
        return True


class FakeHeartbeat:
    def __init__(self):
        self.beats = 0

    def beat(self):
        self.beats += 1


def make_trader(client, watchlist, heartbeat=None, notifier=None):
    return Trader(
        client,
        notifier or FakeNotifier(),
        watchlist,
        game_id="a8db",
        interval=0.01,
        heartbeat=heartbeat or FakeHeartbeat(),
    )


def run(coro):
    return asyncio.run(coro)


def test_places_a_target_and_notifies():
    client = FakeClient(offers={"A": [300, 250]})
    notifier = FakeNotifier()
    trader = make_trader(client, [WatchItem("A", max_buy_cents=500)], notifier=notifier)

    report = run(trader.run_once())

    assert client.created_targets == [("A", 249)]
    assert report.targets_created == 1
    assert "A" in notifier.messages[0]


def test_skips_titles_that_already_have_a_target():
    client = FakeClient(offers={"A": [300]}, targets=[Target("t1", "A")])
    report = run(make_trader(client, [WatchItem("A", 500)]).run_once())
    assert client.created_targets == []
    assert report.targets_created == 0


def test_does_not_spend_more_than_the_balance():
    client = FakeClient(balance=300, offers={"A": [250], "B": [250]})
    watchlist = [WatchItem("A", 500), WatchItem("B", 500)]
    report = run(make_trader(client, watchlist).run_once())
    assert client.created_targets == [("A", 249)]  # the second one no longer fits
    assert report.targets_created == 1


def test_lists_owned_items_once_above_the_floor():
    client = FakeClient(
        offers={"A": [400]},
        targets=[Target("t1", "A")],
        inventory=[InventoryItem("x1", "A"), InventoryItem("x2", "A", in_market=True)],
    )
    report = run(make_trader(client, [WatchItem("A", 500, min_sell_cents=350)]).run_once())
    assert client.created_offers == [("x1", 399)]  # x2 is already on sale
    assert report.offers_created == 1


def test_one_failing_item_does_not_stop_the_others():
    client = FakeClient(offers={"B": [200]})
    client.failing_titles.add("A")
    report = run(make_trader(client, [WatchItem("A", 500), WatchItem("B", 500)]).run_once())
    assert report.errors == 1
    assert client.created_targets == [("B", 199)]


def test_each_cycle_beats_the_heartbeat():
    heartbeat = FakeHeartbeat()
    trader = make_trader(FakeClient(), [WatchItem("A", 500)], heartbeat=heartbeat)
    run(trader.run_once())
    run(trader.run_once())
    assert heartbeat.beats == 2
    assert trader.cycles == 2


def test_run_forever_stops_on_request():
    async def scenario():
        trader = make_trader(FakeClient(offers={"A": [300]}), [WatchItem("A", 500)])
        task = asyncio.create_task(trader.run_forever())
        await asyncio.sleep(0.05)
        trader.request_stop()
        await asyncio.wait_for(task, timeout=2)
        return trader.cycles

    assert asyncio.run(scenario()) >= 1


def test_dry_run_prefix_in_notifications():
    client = FakeClient(offers={"A": [300]})
    client.dry_run = True
    notifier = FakeNotifier()
    run(make_trader(client, [WatchItem("A", 500)], notifier=notifier).run_once())
    assert notifier.messages[0].startswith("[DRY-RUN]")
