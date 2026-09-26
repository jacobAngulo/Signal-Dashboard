"""TB-46: per-producer signal windows (Phase A), native exits (Phase C), the
`trading_days` forward calendar's fail-soft contract (Phase B), and the
/api/signals sim_* contract (Phase E).
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from backend import main, trading_days
from backend.corporate_actions import ContinuousPriceBook
from backend.metrics import _window, enrich


class WindowTests(unittest.TestCase):
    def test_foundry_swing_label_with_no_session_count(self):
        result = _window({"producer": "foundry", "horizon": "swing"})

        self.assertEqual(result["window_label"], "swing")
        self.assertIsNone(result["window_sessions"])
        self.assertEqual(result["window_basis"], "llm_time_sensitivity")

class TradingDaysFailSoftTests(unittest.TestCase):
    def setUp(self):
        trading_days._calendar_built = False
        trading_days._calendar = None

    def tearDown(self):
        trading_days._calendar_built = False
        trading_days._calendar = None

    def test_every_function_returns_none_when_the_calendar_build_raises(self):
        with patch("exchange_calendars.get_calendar", side_effect=RuntimeError("boom")):
            self.assertIsNone(trading_days.session_offset("2026-01-05", 5))
            self.assertIsNone(trading_days.sessions_between("2026-01-05", "2026-01-10"))
            self.assertIsNone(trading_days.is_session("2026-01-05"))

    def test_enrich_still_produces_rows_when_the_calendar_is_down(self):
        frame = pd.DataFrame([{
            "ticker": "AAA", "date": "2026-06-25", "close": 10.0,
            "action_revision": 1, "price_basis": "confirmed_continuous",
            "continuity_segment": "only", "security_id": "sec-a",
            "confirmation_status": "confirmed", "blocked_action_ids": [],
            "policy": "dashboard",
        }])

        class GW:
            def continuous_ohlcv_bulk(self, tickers, **kwargs):
                return frame

        book = ContinuousPriceBook()
        book.load(GW(), ["AAA"])

        class FakeStore:
            all_dates = ["2026-06-25"]
            price_max_date = "2026-06-25"
            producers = {}

            def performance(self, *args, **kwargs):
                return book.performance(*args, **kwargs)

            def series(self, ticker, start=None):
                return book.series(ticker, start=start)

        with patch("exchange_calendars.get_calendar", side_effect=RuntimeError("boom")):
            with patch("backend.metrics.STORE", FakeStore()):
                row = enrich({
                    "id": "x", "producer": "foundry", "date": "2026-06-25",
                    "ticker": "AAA", "decision": "BUY", "horizon": "swing",
                })

        # A missing forward date must never take the row down with it: the row
        # still carries its identity and its entry price.
        self.assertEqual(row["ticker"], "AAA")
        self.assertEqual(row["date"], "2026-06-25")
        self.assertEqual(row["window_label"], "swing")
        self.assertIsNone(row["window_sessions"])
        self.assertIsNotNone(row["entry_px"])


class SignalsSimContractTests(unittest.TestCase):
    """/api/signals: sim_* fields exist only when a request asks for them."""

    ROWS = [
        {"id": "a", "producer": "intrinsic", "date": "2026-07-20", "ticker": "AAA",
         "decision": "BUY", "metric": 0.3, "status_perf": "up"},
        {"id": "b", "producer": "foundry", "date": "2026-07-19", "ticker": "BBB",
         "decision": "SELL", "metric": 0.2, "status_perf": "down"},
    ]

    def test_no_sim_params_means_no_sim_keys_anywhere_in_the_response(self):
        store = SimpleNamespace(producers={"intrinsic": object(), "foundry": object()})
        with (
            patch.object(main, "STORE", store),
            patch.object(main, "enriched_decisions", return_value=list(self.ROWS)),
        ):
            result = main.signals(limit=10, offset=0)

        for row in result["signals"]:
            self.assertNotIn("sim_outcome", row)
        self.assertNotIn("sim", result["summary"])

    def test_sim_params_attach_sim_outcome_to_every_row(self):
        calls = []

        def fake_simulate_exit(ticker, date, **kwargs):
            calls.append((ticker, date, kwargs))
            return {
                "outcome": "target", "exit_date": "2026-07-21", "return": 0.1,
                "sessions_held": 1, "ambiguous": False, "blocked_reason": None,
            }

        store = SimpleNamespace(
            producers={"intrinsic": object(), "foundry": object()},
            simulate_exit=fake_simulate_exit,
        )
        with (
            patch.object(main, "STORE", store),
            patch.object(main, "enriched_decisions", return_value=list(self.ROWS)),
        ):
            result = main.signals(limit=10, offset=0, stop_pct=0.05, target_pct=0.10)

        self.assertEqual(len(result["signals"]), 2)
        for row in result["signals"]:
            self.assertIn("sim_outcome", row)
            self.assertEqual(row["sim_outcome"], "target")
        self.assertIn("sim", result["summary"])
        self.assertEqual(result["summary"]["sim"]["counts"]["target"], 2)
        # side picked per row: SELL simulates as a short.
        sides = {ticker: kwargs["side"] for ticker, _date, kwargs in calls}
        self.assertEqual(sides["AAA"], "long")
        self.assertEqual(sides["BBB"], "short")


if __name__ == "__main__":
    unittest.main()
