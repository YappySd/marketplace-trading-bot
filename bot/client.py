"""Async DMarket API client: signing, throttling, retries and a dry-run guard.

Every method that changes state goes through `_request(..., write=True)`.
While `dry_run` is on, those calls are logged and never sent, so the bot can
be run safely against a real account to see what it *would* do.
"""

from __future__ import annotations

import asyncio
import json
import random
import time

from loguru import logger

from bot.http import HttpResponse, TransportError
from bot.models import Balance, InventoryItem, MarketItem, Target
from bot.money import api_cents, cents_to_dollar_string
from bot.signing import build_path, sign_request

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 60.0


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def _short(text: str) -> str:
    return text[:200].replace("\n", " ")


def _pick(raw: dict, *names: str):
    """First present key among several spellings (APIs are inconsistent)."""
    for name in names:
        if name in raw and raw[name] is not None:
            return raw[name]
    return None


def _items(data: dict, *keys: str) -> list:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


class DMarketClient:
    def __init__(
        self,
        public_key: str,
        secret_key: str,
        transport,
        *,
        base_url: str = "https://api.dmarket.com",
        dry_run: bool = True,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_cap: float = 20.0,
        min_interval: float = 0.25,
        sleep=asyncio.sleep,
        clock=time.monotonic,
        wall_clock=time.time,
        rng=random.random,
    ) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self.dry_run = dry_run
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._rng = rng
        self._throttle_lock = asyncio.Lock()
        self._next_at = 0.0

    # ------------------------------------------------------------------ core

    async def _throttle(self) -> None:
        """Keep at least `min_interval` seconds between requests."""
        async with self._throttle_lock:
            wait = self._next_at - self._clock()
            if wait > 0:
                await self._sleep(wait)
            self._next_at = max(self._clock(), self._next_at) + self._min_interval

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), MAX_RETRY_AFTER)
            except ValueError:
                pass  # HTTP-date form is not supported; fall back to backoff
        ceiling = min(self._backoff_cap, self._backoff_base * (2**attempt))
        return ceiling * (0.5 + 0.5 * self._rng())

    @staticmethod
    def _parse(response: HttpResponse) -> dict:
        if not response.text.strip():
            return {}
        try:
            data = json.loads(response.text)
        except ValueError as exc:
            raise ApiError(response.status, "response is not valid JSON") from exc
        return data if isinstance(data, dict) else {"data": data}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
        write: bool = False,
    ) -> dict:
        body_str = "" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        target = build_path(path, params)

        if write and self.dry_run:
            logger.info("[DRY-RUN] {} {} {}", method, target, body_str)
            return {"dry_run": True}

        last_error = "request failed"
        for attempt in range(self._max_retries + 1):
            await self._throttle()
            headers = sign_request(
                self._public_key, self._secret_key, method, target, body_str, self._wall_clock()
            )
            if body is not None:
                headers["Content-Type"] = "application/json"
            try:
                response = await self._transport.request(
                    method,
                    self._base_url + target,
                    headers=headers,
                    data=body_str.encode("utf-8") if body is not None else None,
                )
            except (TransportError, OSError) as exc:
                last_error = f"network error: {type(exc).__name__}"
                if attempt >= self._max_retries:
                    break
                await self._sleep(self._delay(attempt, None))
                continue

            if response.status in RETRY_STATUSES:
                last_error = f"HTTP {response.status}: {_short(response.text)}"
                if attempt >= self._max_retries:
                    raise ApiError(response.status, _short(response.text))
                retry_after = {k.lower(): v for k, v in response.headers.items()}.get("retry-after")
                await self._sleep(self._delay(attempt, retry_after))
                continue

            if response.status >= 400:
                raise ApiError(response.status, _short(response.text))
            return self._parse(response)

        raise ApiError(0, last_error)

    # ------------------------------------------------------------------ reads

    async def get_balance(self) -> Balance:
        data = await self._request("GET", "/account/v1/balance")
        return Balance(usd_cents=api_cents(data.get("usd", 0)))

    async def get_market_items(self, game_id: str, title: str, limit: int = 10) -> list[MarketItem]:
        data = await self._request(
            "GET",
            "/exchange/v1/market/items",
            params={
                "gameId": game_id,
                "title": title,
                "currency": "USD",
                "limit": limit,
                "orderBy": "price",
                "orderDir": "asc",
            },
        )
        result = []
        for raw in _items(data, "objects", "items"):
            try:
                result.append(
                    MarketItem(
                        title=raw["title"],
                        price_cents=api_cents(raw["price"]["USD"]),
                        item_id=str(raw.get("itemId", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.debug("Skipped a market item with an unexpected shape")
        return result

    async def list_targets(self, game_id: str) -> list[Target]:
        data = await self._request(
            "GET",
            "/marketplace-api/v2/user/targets",
            params={"gameId": game_id, "status": "TargetStatusActive", "limit": 100},
        )
        result = []
        for raw in _items(data, "Items", "items", "targets"):
            target_id = _pick(raw, "TargetID", "targetId", "id")
            title = _pick(raw, "Title", "title")
            if target_id is not None and title is not None:
                result.append(Target(target_id=str(target_id), title=str(title)))
        return result

    async def get_inventory(self, game_id: str) -> list[InventoryItem]:
        data = await self._request(
            "GET",
            "/marketplace-api/v2/user/inventory",
            params={"gameId": game_id, "limit": 100},
        )
        result = []
        for raw in _items(data, "Items", "items", "objects"):
            asset_id = _pick(raw, "AssetID", "assetId", "itemId")
            title = _pick(raw, "Title", "title")
            if asset_id is not None and title is not None:
                result.append(
                    InventoryItem(
                        asset_id=str(asset_id),
                        title=str(title),
                        in_market=bool(_pick(raw, "InMarket", "inMarket")),
                    )
                )
        return result

    # ----------------------------------------------------------------- writes

    async def create_target(self, game_id: str, title: str, price_cents: int, amount: int = 1) -> dict:
        body = {
            "GameID": game_id,
            "Targets": [
                {
                    "Amount": amount,
                    "Price": {"Amount": cents_to_dollar_string(price_cents), "Currency": "USD"},
                    "Title": title,
                }
            ],
        }
        return await self._request("POST", "/exchange/v1/target/create", body=body, write=True)

    async def delete_target(self, target_id: str) -> dict:
        body = {"Targets": [{"TargetID": target_id}]}
        return await self._request("POST", "/exchange/v1/target/delete", body=body, write=True)

    async def create_offer(self, asset_id: str, price_cents: int) -> dict:
        body = {
            "Offers": [
                {
                    "AssetID": asset_id,
                    "Price": {"Currency": "USD", "Amount": round(price_cents / 100, 2)},
                }
            ]
        }
        return await self._request("POST", "/marketplace-api/v1/user-offers/create", body=body, write=True)
