"""Admission control for a tokens-per-minute quota.

The intuition that matters: the binding constraint on a fan-out is the **burst at
request start**, not the sustained draw. Fifty packs firing at once is roughly a
million input tokens in one instant — far over a 500k/min ceiling — even though
once they are all streaming the aggregate rate is modest. So the gate charges a
request its full estimated cost when it is admitted, and holds the next one back
until the rolling window has room.

Charging the whole estimate up front is deliberately pessimistic. A request's
output is spent over the minutes it streams, not at admission, so the gate
under-utilises the quota rather than discovering the ceiling as a wall of 429s
halfway through a run that has already spent real money.
"""
from __future__ import annotations

import threading
import time
from collections import deque

WINDOW = 60.0


class RateGate:
    def __init__(self, tpm: int, rpm: int, buffer: float = 0.30):
        self.tok_budget = max(1.0, tpm * (1.0 - buffer))
        self.req_budget = max(1.0, rpm * (1.0 - buffer))
        self._events: deque[tuple[float, float]] = deque()
        self._lock = threading.Lock()
        self.waited = 0.0

    def _trim(self, now: float) -> tuple[float, int]:
        while self._events and now - self._events[0][0] > WINDOW:
            self._events.popleft()
        return sum(t for _, t in self._events), len(self._events)

    def acquire(self, tokens: float) -> float:
        """Block until `tokens` fit in the rolling window. Returns seconds waited."""
        t0 = time.monotonic()
        while True:
            with self._lock:
                now = time.monotonic()
                used, count = self._trim(now)
                # An oversized single request would never fit and would deadlock
                # the whole run; let it through alone rather than stall forever.
                fits = (used + tokens <= self.tok_budget and count + 1 <= self.req_budget)
                if fits or not self._events:
                    self._events.append((now, tokens))
                    w = time.monotonic() - t0
                    self.waited += w
                    return w
                wait = WINDOW - (now - self._events[0][0])
            time.sleep(min(max(wait, 0.05), 5.0))


def estimate_tokens(text: str, max_output: int, output_fraction: float = 1.0) -> float:
    """Rough token cost of one request.

    ~3.5 chars/token is a deliberate under-estimate of characters-per-token for
    Devanagari and other non-Latin scripts, which tokenise far less efficiently
    than English. Under-estimating chars/token over-estimates the token count,
    which is the safe direction for a rate gate.
    """
    return len(text) / 3.5 + max_output * output_fraction
