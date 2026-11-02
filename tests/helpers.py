"""Shared fakes for the tests (no network, no real sleeping)."""

from __future__ import annotations

import json

from bot.http import HttpResponse

# Deterministic fake credentials (a throwaway seed, not a real key).
PUBLIC_KEY = "ab" * 32
SECRET_KEY = "11" * 32 + "cd" * 32  # 32-byte seed + 32 filler bytes, like the real 64-byte form


class FakeTransport:
    """Records requests and replays queued responses (or exceptions)."""

    def __init__(self, responses=None):
        self.requests = []
        self._responses = list(responses or [])

    def queue(self, status=200, body=None, headers=None):
        text = body if isinstance(body, str) else json.dumps(body if body is not None else {})
        self._responses.append(HttpResponse(status, text, headers or {}))

    def queue_error(self, exc):
        self._responses.append(exc)

    async def request(self, method, url, headers=None, data=None, timeout=15.0):
        self.requests.append({"method": method, "url": url, "headers": headers or {}, "data": data})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        pass


class FakeSleep:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)
