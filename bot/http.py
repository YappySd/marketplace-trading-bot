"""A tiny HTTP seam so the client can be tested without a network.

`AiohttpTransport` is the real implementation. Tests pass a fake object with
the same `request` / `close` methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class TransportError(OSError):
    """Network-level failure (connection, timeout). Safe to retry."""


@dataclass
class HttpResponse:
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)


class AiohttpTransport:
    def __init__(self) -> None:
        self._session = None

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float = 15.0,
    ) -> HttpResponse:
        import aiohttp
        from yarl import URL

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        # encoded=True keeps the URL exactly as signed; without it yarl may
        # re-encode the query and the signature would no longer match.
        target = URL(url, encoded=True)
        try:
            async with self._session.request(
                method,
                target,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                text = await resp.text()
                return HttpResponse(resp.status, text, dict(resp.headers))
        except aiohttp.ClientError as exc:
            # Only the class name: some messages contain the full URL.
            raise TransportError(type(exc).__name__) from exc

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
