"""Admission control.

The gate exists because a fan-out's binding constraint is the burst at request
start, not the sustained draw — 49 packs firing at once is ~1M input tokens in
one instant against a 500k/min ceiling.
"""
import time

from dispogen.ratelimit import RateGate, estimate_tokens


def test_the_buffer_is_actually_withheld():
    g = RateGate(500_000, 500, 0.30)
    assert g.tok_budget == 350_000
    assert g.req_budget == 350


def test_requests_inside_the_budget_are_not_delayed():
    g = RateGate(500_000, 500, 0.30)
    t0 = time.monotonic()
    for _ in range(3):
        g.acquire(100_000)
    assert time.monotonic() - t0 < 0.5


def test_the_budget_throttles_rather_than_overshooting():
    """Four 100k requests do not fit in a 350k window; the fourth must wait."""
    g = RateGate(500_000, 500, 0.30)
    for _ in range(3):
        g.acquire(100_000)
    assert sum(t for _, t in g._events) == 300_000
    # Rather than sleep through a real 60s window, check the gate's own view.
    used, count = g._trim(time.monotonic())
    assert used + 100_000 > g.tok_budget, "the 4th request must not fit"


def test_the_request_count_limit_binds_independently_of_tokens():
    g = RateGate(10 ** 9, 3, 0.0)
    for _ in range(3):
        g.acquire(1)
    used, count = g._trim(time.monotonic())
    assert count == 3 and count + 1 > g.req_budget


def test_an_oversized_request_goes_through_alone_rather_than_deadlocking():
    """A single request larger than the whole budget can never fit.

    Blocking it forever would stall the run with no error and no output — worse
    than exceeding the quota once and taking the 429.
    """
    g = RateGate(1000, 500, 0.0)
    t0 = time.monotonic()
    g.acquire(50_000)
    assert time.monotonic() - t0 < 0.5


def test_old_events_leave_the_rolling_window():
    g = RateGate(500_000, 500, 0.30)
    g._events.append((time.monotonic() - 61.0, 300_000))
    used, count = g._trim(time.monotonic())
    assert used == 0 and count == 0


def test_the_estimate_errs_high_for_non_latin_text():
    """Devanagari tokenises far less efficiently than English.

    Under-estimating chars-per-token over-estimates the token count, which is the
    safe direction for a rate gate.
    """
    hindi = "मैंने बैंक में जमा कर दिया था" * 40
    assert estimate_tokens(hindi, 0) > len(hindi) / 4


def test_the_output_fraction_scales_the_charge():
    a = estimate_tokens("x" * 3500, 100_000, 1.0)
    b = estimate_tokens("x" * 3500, 100_000, 0.5)
    assert a - b == 50_000
