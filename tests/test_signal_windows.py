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
from backend.metrics import _native_exit, _window, enrich


class WindowTests(unittest.TestCase):
    def test_lstm_buy_6m_window(self):
        result = _window({"producer": "lstm", "horizon": "6m"})

        self.assertEqual(result["window_label"], "6m")
        self.assertEqual(result["window_sessions"], 126)
        self.assertEqual(result["window_basis"], "producer_horizon")

    def test_lstm_watch_uses_attention_horizon_not_best_horizon(self):
        result = _window({
            "producer": "lstm", "tier": "lstm_attention",
            "attention_horizon_sessions": 5.0, "best_horizon": "6m",
        })

        self.assertEqual(result["window_sessions"], 5)
        self.assertEqual(result["window_basis"], "attention_horizon")
        self.assertNotEqual(result["window_sessions"], 126)

    def test_lstm_watch_falls_back_to_best_horizon_when_attention_field_missing(self):
        result = _window({
            "producer": "lstm", "tier": "lstm_attention",
            "attention_horizon_sessions": None, "best_horizon": "1m",
        })

        self.assertEqual(result["window_sessions"], 21)
        self.assertEqual(result["window_basis"], "producer_horizon")

    def test_intrinsic_window_is_always_none(self):
        result = _window({"producer": "intrinsic", "horizon": "irrelevant"})

        self.assertIsNone(result["window_label"])
        self.assertIsNone(result["window_sessions"])
        self.assertIsNone(result["window_basis"])
        self.assertIsNotNone(result["window_note"])

    def test_foundry_swing_label_with_no_session_count(self):
        result = _window({"producer": "foundry", "horizon": "swing"})

        self.assertEqual(result["window_label"], "swing")
        self.assertIsNone(result["window_sessions"])
        self.assertEqual(result["window_basis"], "llm_time_sensitivity")

    def test_unknown_lstm_horizon_passes_through_label_with_no_sessions(self):
        # Never guess: an unrecognized horizon string still shows up verbatim,
        # but with no invented session count.
        result = _window({"producer": "lstm", "horizon": "3q"})

        self.assertEqual(result["window_label"], "3q")
        self.assertIsNone(result["window_sessions"])


class FakeIntrinsicStore:
    """Just enough of Store for `_native_exit`'s intrinsic branch: a score
    history to search for the status flip, plus a fixed performance/series
    answer so the surrounding return computation never touches the network."""

    def __init__(self, history):
        self.producers = {"intrinsic": SimpleNamespace(history=history)}

    def producer_status_exit(self, producer, ticker, after_date, status):
        for row in self.producers[producer].history.get(ticker, []):
            if row["date"] > after_date and row.get("status") == status:
                return row["date"]
        return None

    def performance(self, ticker, entry_date, *, sessions=None, **_kwargs):
        return {"return": 0.25, "exit": {"date": "2026-01-20", "px": 15.0}}

    def series(self, ticker, start=None):
        return []


class IntrinsicNativeExitTests(unittest.TestCase):
    def test_resolves_closed_when_status_flips_to_exit_candidate(self):
        history = {"AAA": [
            {"date": "2026-01-05", "status": "buy_candidate"},
            {"date": "2026-01-12", "status": "buy_candidate"},
            {"date": "2026-01-20", "status": "exit_candidate"},
        ]}
        with patch("backend.metrics.STORE", FakeIntrinsicStore(history)):
            result = _native_exit(
                {"producer": "intrinsic", "ticker": "AAA"}, "2026-01-05", None)

        self.assertEqual(result["exit_state"], "closed")
        self.assertEqual(result["exit_date"], "2026-01-20")
        self.assertEqual(result["exit_basis"], "producer_status")

    def test_stays_open_when_status_never_flips(self):
        history = {"AAA": [
            {"date": "2026-01-05", "status": "buy_candidate"},
            {"date": "2026-01-12", "status": "buy_candidate"},
        ]}
        with patch("backend.metrics.STORE", FakeIntrinsicStore(history)):
            result = _native_exit(
                {"producer": "intrinsic", "ticker": "AAA"}, "2026-01-05", None)

        self.assertEqual(result["exit_state"], "open")
        self.assertIsNone(result["exit_date"])
        self.assertIsNotNone(result["exit_note"])


class LstmNativeExitTests(unittest.TestCase):
    def test_mature_exit_keeps_its_date_when_return_is_ca_blocked(self):
        store = SimpleNamespace(
            performance=lambda *_args, **_kwargs: {
                "return": None,
                "blocked_reason": "corporate_action_unresolved",
                "exit": {"date": "2026-06-10", "px": 12.5},
            },
        )
        with patch("backend.metrics.STORE", store):
            result = _native_exit(
                {"producer": "lstm", "ticker": "AAA"},
                "2026-05-11",
                21,
            )

        self.assertEqual(result["exit_state"], "closed")
        self.assertEqual(result["exit_date"], "2026-06-10")
        self.assertEqual(result["exit_px"], 12.5)
        self.assertIsNone(result["exit_return"])
        self.assertEqual(result["sessions_elapsed"], 21)
        self.assertIn("unresolved corporate action", result["exit_note"])


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
                    "id": "x", "producer": "lstm", "date": "2026-06-25",
                    "ticker": "AAA", "decision": "BUY", "horizon": "6m",
                })

        # A missing forward date must never take the row down with it.
        self.assertEqual(row["window_sessions"], 126)
        self.assertEqual(row["exit_state"], "open")
        self.assertIsNone(row["exit_date"])


class SignalsSimContractTests(unittest.TestCase):
    """/api/signals: sim_* fields exist only when a request asks for them."""

    ROWS = [
        {"id": "a", "producer": "lstm", "date": "2026-07-20", "ticker": "AAA",
         "decision": "BUY", "metric": 0.3, "status_perf": "up"},
        {"id": "b", "producer": "foundry", "date": "2026-07-19", "ticker": "BBB",
         "decision": "SELL", "metric": 0.2, "status_perf": "down"},
    ]

    def test_no_sim_params_means_no_sim_keys_anywhere_in_the_response(self):
        store = SimpleNamespace(producers={"lstm": object(), "foundry": object()})
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
            producers={"lstm": object(), "foundry": object()},
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
