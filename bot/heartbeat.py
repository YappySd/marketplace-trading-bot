"""Heartbeat file: the trader touches it every cycle, the watchdog reads its age."""

from __future__ import annotations

import os
import time
from pathlib import Path


class Heartbeat:
    def __init__(self, path: Path, clock=time.time) -> None:
        self._path = Path(path)
        self._clock = clock

    def beat(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(str(self._clock()), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic: the reader never sees half a file

    def age(self) -> float | None:
        """Seconds since the last beat, or None if there has been none."""
        try:
            last = float(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return max(0.0, self._clock() - last)
