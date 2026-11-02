"""Entry point:  python -m bot.main"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loguru import logger

from bot.client import DMarketClient
from bot.config import ConfigError, load_settings
from bot.control import ControlPanel
from bot.heartbeat import Heartbeat
from bot.http import AiohttpTransport
from bot.notifier import TelegramNotifier
from bot.runner import TraderRunner
from bot.trader import Trader
from bot.watchlist import load_watchlist


def setup_logging(log_file: Path) -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_file, level="INFO", rotation="5 MB", retention=5, encoding="utf-8")


async def amain() -> None:
    settings = load_settings()
    setup_logging(settings.log_file)
    watchlist = load_watchlist(settings.watchlist_path)

    transport = AiohttpTransport()
    client = DMarketClient(
        settings.public_key,
        settings.secret_key,
        transport,
        base_url=settings.base_url,
        dry_run=settings.dry_run,
    )
    notifier = TelegramNotifier(settings.telegram_token, settings.telegram_chat_id, transport)
    trader = Trader(
        client,
        notifier,
        watchlist,
        game_id=settings.game_id,
        interval=settings.scan_interval,
        heartbeat=Heartbeat(settings.heartbeat_file),
    )
    runner = TraderRunner(trader, dry_run=settings.dry_run)

    mode = "DRY-RUN" if settings.dry_run else "LIVE"
    logger.info("Starting in {} mode", mode)
    try:
        runner.start()
        await notifier.send(f"Бот запущен ({mode}).")
        if settings.telegram_enabled:
            panel = ControlPanel(notifier, runner, chat_id=settings.telegram_chat_id, log_file=settings.log_file)
            await panel.poll_forever()
        else:
            await asyncio.Event().wait()  # no panel: just keep trading until Ctrl+C
    finally:
        await runner.stop()
        await transport.close()


def run() -> None:
    try:
        asyncio.run(amain())
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")
    except ValueError as exc:  # bad watchlist
        sys.exit(f"Error: {exc}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
