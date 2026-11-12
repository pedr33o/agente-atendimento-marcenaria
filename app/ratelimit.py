from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date


class RateLimiter:
    def __init__(self, max_calls: int = 20, window: float = 60.0, clock=time.monotonic):
        self.max_calls = max_calls
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            now = self.clock()
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.max_calls:
                return False
            hits.append(now)
            return True


class DailyBudget:
    def __init__(self, limit: int, today=date.today):
        self.limit = limit
        self._today = today
        self._day = None
        self._used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            d = self._today()
            if d != self._day:
                self._day, self._used = d, 0
            if self.limit > 0 and self._used >= self.limit:
                return False
            self._used += 1
            return True
