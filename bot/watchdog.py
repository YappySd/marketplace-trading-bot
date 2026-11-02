"""Supervisor: keeps the bot process alive.

It restarts the bot when the process exits, or when it is still running but its
heartbeat file has gone stale (a hung event loop, a stuck request, etc.).
Restarts back off exponentially so a crash loop does not spin the CPU.

Run it instead of the bot:  python -m bot.watchdog
"""

from __future__ import annotations

import subprocess
import sys
import time

from loguru import logger

from bot.config import load_settings
from bot.heartbeat import Heartbeat
from bot.main import setup_logging


class Supervisor:
    def __init__(
        self,
        command: list[str],
        heartbeat_age,
        *,
        stale_after: float = 120.0,
        grace: float = 60.0,
        restart_delay: float = 5.0,
        max_restart_delay: float = 300.0,
        healthy_after: float = 300.0,
        spawn=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._command = command
        self._heartbeat_age = heartbeat_age
        self._stale_after = stale_after
        self._grace = grace
        self._base_delay = restart_delay
        self._delay = restart_delay
        self._max_delay = max_restart_delay
        self._healthy_after = healthy_after
        self._spawn = spawn or (lambda cmd: subprocess.Popen(cmd))
        self._clock = clock
        self._sleep = sleep
        self._proc = None
        self._started_at = 0.0
        self.restarts = 0

    def _start(self) -> None:
        self._proc = self._spawn(self._command)
        self._started_at = self._clock()
        logger.info("Bot process started")

    def _terminate(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _restart(self, reason: str) -> str:
        if self._clock() - self._started_at >= self._healthy_after:
            self._delay = self._base_delay  # it ran fine for a while: reset the backoff
        logger.warning("Restarting the bot ({}), waiting {:.0f}s", reason, self._delay)
        self._sleep(self._delay)
        self._delay = min(self._delay * 2, self._max_delay)
        self.restarts += 1
        self._start()
        return reason

    def step(self) -> str:
        """One supervision pass. Returns started / ok / crashed / stale."""
        if self._proc is None:
            self._start()
            return "started"
        if self._proc.poll() is not None:
            return self._restart("crashed")
        if self._clock() - self._started_at >= self._grace:
            age = self._heartbeat_age()
            if age is None or age > self._stale_after:
                self._terminate()
                return self._restart("stale")
        return "ok"

    def run(self, poll_interval: float = 5.0) -> None:
        try:
            while True:
                self.step()
                self._sleep(poll_interval)
        finally:
            self._terminate()


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_file)
    heartbeat = Heartbeat(settings.heartbeat_file)
    supervisor = Supervisor([sys.executable, "-m", "bot.main"], heartbeat.age)
    try:
        supervisor.run()
    except KeyboardInterrupt:
        logger.info("Watchdog stopped")


if __name__ == "__main__":
    main()
