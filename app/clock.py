from __future__ import annotations

import time


class ChessClock:
    def __init__(self, initial_ms: int) -> None:
        self.remaining = {True: initial_ms, False: initial_ms}
        self.active: bool | None = None
        self.started_ns: int | None = None

    def start(self, color: bool) -> None:
        self.active = color
        self.started_ns = time.monotonic_ns()

    def stop(self) -> int:
        if self.active is None or self.started_ns is None:
            return 0
        elapsed = max(0, (time.monotonic_ns() - self.started_ns) // 1_000_000)
        self.remaining[self.active] = max(0, self.remaining[self.active] - elapsed)
        self.active = None
        self.started_ns = None
        return elapsed

    def value(self, color: bool) -> int:
        value = self.remaining[color]
        if self.active == color and self.started_ns is not None:
            elapsed = (time.monotonic_ns() - self.started_ns) // 1_000_000
            return max(0, value - elapsed)
        return value
