"""TB-46: stop-loss / take-profit historical simulation.

`ContinuousPriceBook.simulate_exit` is a read-only replay over daily
high/low/close bars already held in the price book -- no execution state, no
order book. These tests build synthetic bars (no network), matching the
fixture style in test_corporate_action_performance.py, and exercise the
algorithm in docs/TB-46-signal-windows-plan.md Phase D2 directly.
"""
import unittest
from unittest.mock import patch

import pandas as pd

from backend.corporate_actions import ContinuousPriceBook


class Gateway:
    """Hands back a fixed frame regardless of what the book asks for."""

    def __init__(self, frame):
        self.frame = frame

    def continuous_ohlcv_bulk(self, tickers, **kwargs):
        return self.frame


def bar(date, close, *, high=None, low=None, open_=None,
        confirmation_status="confirmed", blocked_action_ids=None,
        continuity_segment="only", action_revision=1,
        price_basis="confirmed_continuous", ticker="AAA"):
    """One synthetic daily bar in the shape the dashboard continuity gateway
    returns. `high`/`low` default to `close` so a test only has to specify the
    values that matter for it."""
    return {
        "ticker": ticker,
        "date": date,
        "close": close,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close,
        "low": low if low is not None else close,
        "volume": 1000,
        "action_revision": action_revision,
        "price_basis": price_basis,
        "continuity_segment": continuity_segment,
        "security_id": "sec-a",
        "confirmation_status": confirmation_status,
        "blocked_action_ids": blocked_action_ids or [],
        "policy": "dashboard",
    }


def make_book(bars, ticker="AAA"):
    book = ContinuousPriceBook()
    book.load(Gateway(pd.DataFrame(bars)), [ticker])
    return book


class ExitSimulationTests(unittest.TestCase):
    def test_long_stop_hit_exits_at_the_stop_price(self):
        book = make_book([
            bar("2026-01-02", 100, high=101, low=99),
            bar("2026-01-05", 95, high=100, low=94),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertEqual(result["outcome"], "stop")
        self.assertEqual(result["exit_px"], 95.0)
        self.assertEqual(result["exit_date"], "2026-01-05")
        self.assertEqual(result["sessions_held"], 1)
        self.assertFalse(result["ambiguous"])
        self.assertAlmostEqual(result["return"], -0.05)
        self.assertIsNone(result["blocked_reason"])

    def test_long_target_hit(self):
        book = make_book([
            bar("2026-01-02", 100),
            bar("2026-01-05", 108, high=111, low=99),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertEqual(result["outcome"], "target")
        self.assertAlmostEqual(result["exit_px"], 110.0)
        self.assertFalse(result["ambiguous"])
        self.assertAlmostEqual(result["return"], 0.10)

    def test_both_thresholds_in_one_bar_is_ambiguous_and_resolves_stop(self):
        # Same-bar ambiguity: the conservative read is the loss (Ground truth
        # measured this at 0-0.5% of cases across the reference thresholds).
        book = make_book([
            bar("2026-01-02", 100),
            bar("2026-01-05", 100, high=115, low=90),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertTrue(result["ambiguous"])
        self.assertEqual(result["outcome"], "stop")
        self.assertEqual(result["exit_px"], 95.0)

    def test_neither_threshold_and_window_completes_is_held_with_a_real_return(self):
        book = make_book([
            bar("2026-01-02", 100),
            bar("2026-01-05", 101, high=102, low=99),
            bar("2026-01-06", 102, high=103, low=100),
            bar("2026-01-07", 101, high=103, low=99),
            bar("2026-01-08", 103, high=104, low=100),
            bar("2026-01-09", 103, high=104, low=101),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertEqual(result["outcome"], "held")
        self.assertEqual(result["exit_px"], 103.0)
        self.assertEqual(result["exit_date"], "2026-01-09")
        self.assertEqual(result["sessions_held"], 5)
        self.assertAlmostEqual(result["return"], 0.03)

    def test_window_runs_past_available_data_is_open_not_held(self):
        # "held" means the rule never fired; "open" means we don't know yet.
        # Only one bar of data exists past entry, but the window asks for 5.
        book = make_book([
            bar("2026-01-02", 100),
            bar("2026-01-05", 101, high=102, low=99),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertEqual(result["outcome"], "open")
        self.assertIsNone(result["return"])
        self.assertNotEqual(result["outcome"], "held")

    def test_window_crossing_unresolved_corporate_action_blocks_the_whole_result(self):
        book = make_book([
            bar("2026-01-02", 100, continuity_segment="before"),
            bar("2026-01-05", 100, high=101, low=99, continuity_segment="after",
                confirmation_status="conflict", blocked_action_ids=["act-1"]),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertIsNone(result["outcome"])
        self.assertEqual(result["blocked_reason"], "corporate_action_unresolved")

    def test_trigger_before_the_boundary_is_reported_even_though_a_later_bar_would_block(self):
        # The guard is incremental, not window-wide: a trade that already
        # exited on day 1 must not be retroactively poisoned by an action
        # that only shows up on day 2, which the walk never reaches.
        book = make_book([
            bar("2026-01-02", 100, continuity_segment="before"),
            bar("2026-01-05", 95, high=100, low=94, continuity_segment="before"),
            bar("2026-01-06", 95, high=96, low=94, continuity_segment="after",
                confirmation_status="conflict", blocked_action_ids=["act-1"]),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)

        self.assertEqual(result["outcome"], "stop")
        self.assertIsNone(result["blocked_reason"])
        self.assertEqual(result["sessions_held"], 1)

    def test_short_side_mirrors_stop_and_target(self):
        # Foundry SELL rows: a short profits as price falls, so its stop sits
        # above entry and the triggers swap high/low.
        book = make_book([
            bar("2026-01-02", 100),
            bar("2026-01-05", 104, high=106, low=99),
        ])

        result = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5, side="short")

        self.assertEqual(result["outcome"], "stop")
        self.assertEqual(result["exit_px"], 105.0)
        self.assertAlmostEqual(result["return"], -0.05)

    def test_trailing_stop_ratchets_and_fires_where_a_fixed_stop_would_not(self):
        bars = [
            bar("2026-01-02", 100),
            bar("2026-01-05", 115, high=120, low=99),
            bar("2026-01-06", 118, high=121, low=110),
        ]

        fixed = make_book(bars).simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=None, max_sessions=2,
            trailing=False)
        self.assertEqual(fixed["outcome"], "held")

        trailing = make_book(bars).simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=None, max_sessions=2,
            trailing=True)
        self.assertEqual(trailing["outcome"], "stop")
        self.assertEqual(trailing["exit_px"], 114.0)  # 120 * (1 - 0.05), ratcheted on day 1
        self.assertEqual(trailing["sessions_held"], 2)

    def test_entry_index_parity_with_performance_across_snap_modes(self):
        """`simulate_exit` and `performance` share `_entry_index`; this proves
        they can never resolve a different entry session for the same
        (ticker, date, entry_snap)."""
        bars = [
            bar("2026-06-25", 3.0, continuity_segment="before"),
            bar("2026-06-26", 3.0, continuity_segment="after"),
            bar("2026-06-29", 3.3, continuity_segment="after"),
        ]
        cases = (
            ("before", "2026-06-29"),
            ("on_or_before", "2026-06-28"),
            (None, "2026-06-26"),
        )
        for snap, date in cases:
            with self.subTest(entry_snap=snap):
                book = make_book(bars)
                perf = book.performance("AAA", date, sessions=1, entry_snap=snap)
                sim = book.simulate_exit(
                    "AAA", date, stop=0.05, target=None, max_sessions=1,
                    entry_snap=snap)
                expected_entry_px = perf["entry"]["px"]
                self.assertAlmostEqual(sim["stop_px"], expected_entry_px * 0.95)

    def test_simulate_exit_cache_is_cleared_on_reload(self):
        """D3: a stale cache across a price refresh must never serve an exit
        computed from retired prices."""
        book = make_book([
            bar("2026-01-02", 100),
            bar("2026-01-05", 95, high=100, low=94),
        ])
        first = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)
        self.assertEqual(first["outcome"], "stop")

        # Reload with different prices under the same cache key.
        book.load(Gateway(pd.DataFrame([
            bar("2026-01-02", 100),
            bar("2026-01-05", 108, high=111, low=99),
        ])), ["AAA"])
        second = book.simulate_exit(
            "AAA", "2026-01-02", stop=0.05, target=0.10, max_sessions=5)
        self.assertEqual(second["outcome"], "target")


if __name__ == "__main__":
    unittest.main()
