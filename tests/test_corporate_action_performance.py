import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pandas as pd

from backend.corporate_actions import ContinuousPriceBook, HTTPGateway
from backend.metrics import analytics, enrich
from backend.store import Store


class Gateway:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def continuous_ohlcv_bulk(self, tickers, **kwargs):
        self.calls.append((tickers, kwargs))
        return self.frame


def bars(status="confirmed", blocked=None):
    return pd.DataFrame(
        [
            {
                "ticker": "AAA", "date": "2026-06-25", "close": 3.0,
                "action_revision": 4, "price_basis": "confirmed_continuous",
                "continuity_segment": "before", "security_id": "sec-a",
                "confirmation_status": "confirmed", "blocked_action_ids": [],
                "policy": "dashboard",
            },
            {
                "ticker": "AAA", "date": "2026-06-26", "close": 3.0,
                "action_revision": 4, "price_basis": "confirmed_continuous",
                "continuity_segment": "after", "security_id": "sec-a",
                "confirmation_status": status, "blocked_action_ids": blocked or [],
                "policy": "dashboard",
            },
            {
                "ticker": "AAA", "date": "2026-06-29", "close": 3.3,
                "action_revision": 4, "price_basis": "confirmed_continuous",
                "continuity_segment": "after", "security_id": "sec-a",
                "confirmation_status": status, "blocked_action_ids": blocked or [],
                "policy": "dashboard",
            },
        ]
    )


class CorporateActionPerformanceTests(unittest.TestCase):
    def test_http_gateway_posts_bulk_continuity_contract(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b"[]"

        with patch("backend.corporate_actions.urlopen", return_value=Response()) as request:
            result = HTTPGateway("http://127.0.0.1:8765").continuous_ohlcv_bulk(
                ["AAA"], start="2026-06-25", policy="dashboard", strict=False
            )

        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "http://127.0.0.1:8765/continuous-ohlcv/bulk")
        self.assertEqual(
            json.loads(sent.data),
            {
                "tickers": ["AAA"], "start": "2026-06-25",
                "policy": "dashboard", "strict": False,
            },
        )
        self.assertEqual(result, [])

    def test_http_gateway_requests_bounded_intraday_contract(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'[{"ticker":"ALAB","timeframe":"5Min"}]'

        with patch("backend.corporate_actions.urlopen", return_value=Response()) as request:
            result = HTTPGateway("http://127.0.0.1:8765").intraday_ohlcv(
                "alab",
                start="2026-07-27T00:00:00+00:00",
                end="2026-07-28T00:00:00+00:00",
                timeframe="5Min",
                feed="sip",
                policy="dashboard",
            )

        sent = request.call_args.args[0]
        parsed = urlparse(sent.full_url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/market-data/intraday")
        self.assertEqual(query["ticker"], ["ALAB"])
        self.assertEqual(query["timeframe"], ["5Min"])
        self.assertEqual(query["feed"], ["sip"])
        self.assertEqual(query["policy"], ["dashboard"])
        self.assertEqual(result[0]["ticker"], "ALAB")

    def test_failed_refresh_keeps_last_confirmed_price_snapshot(self):
        class FailingGateway:
            def continuous_ohlcv_bulk(self, _tickers, **_kwargs):
                raise RuntimeError("gateway briefly unavailable")

            def close(self):
                return None

        store = Store(gateway_factory=FailingGateway)
        store.price_book.load(Gateway(bars()), ["AAA"])
        store.prices = {
            "AAA": (
                [row["date"] for row in store.price_book.points["AAA"]],
                [row["px"] for row in store.price_book.points["AAA"]],
            )
        }
        previous_points = store.price_book.points

        store._build_prices((frozenset({"AAA"}), "2026-06-25"))

        self.assertIs(store.price_book.points, previous_points)
        self.assertIn("AAA", store.prices)
        self.assertEqual(store.price_max_date, "2026-06-29")
        self.assertEqual(store.price_load_error, "gateway briefly unavailable")

    @patch("backend.corporate_actions.time.sleep")
    def test_price_book_resumes_after_brief_gateway_disconnect(self, sleep):
        class FlakyGateway:
            def __init__(self):
                self.calls = 0

            def continuous_ohlcv_bulk(self, _tickers, **_kwargs):
                self.calls += 1
                if self.calls < 3:
                    raise ConnectionResetError("snapshot restart")
                return bars()

        gateway = FlakyGateway()
        book = ContinuousPriceBook()

        book.load(gateway, ["AAA"])

        self.assertIn("AAA", book.points)
        self.assertEqual(gateway.calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 4.0])

    def test_confirmed_continuous_sessions_remove_mechanical_split_jump(self):
        gateway = Gateway(bars())
        book = ContinuousPriceBook()
        book.load(gateway, ["AAA"], start="2026-06-25")
        result = book.performance("AAA", "2026-06-25", sessions=1)
        self.assertEqual(result["return"], 0.0)
        self.assertIsNone(result["blocked_reason"])
        self.assertEqual(result["continuity_segments"], ["before", "after"])
        self.assertEqual(
            gateway.calls[0][1],
            {"start": "2026-06-25", "end": None, "policy": "dashboard", "strict": False},
        )

    def test_price_book_preserves_gateway_ohlcv_for_trading_chart(self):
        frame = bars()
        frame["open"] = [2.9, 3.0, 3.1]
        frame["high"] = [3.1, 3.2, 3.4]
        frame["low"] = [2.8, 2.9, 3.0]
        frame["volume"] = [1000, 1500, 2200]
        frame["source_symbol"] = "AAA"
        frame["data_source"] = "alpaca_sip_raw"
        book = ContinuousPriceBook()

        book.load(Gateway(frame), ["AAA"])

        latest = book.series("AAA")[-1]
        self.assertEqual(
            {key: latest[key] for key in ("open", "high", "low", "close", "volume")},
            {"open": 3.1, "high": 3.4, "low": 3.0, "close": 3.3, "volume": 2200.0},
        )
        self.assertEqual(latest["px"], latest["close"])
        self.assertEqual(latest["data_source"], "alpaca_sip_raw")

    def test_future_entry_session_is_pending_with_last_point(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars()), ["AAA"])
        result = book.performance("AAA", "2026-06-30", sessions=1)
        self.assertIsNone(result["return"])
        self.assertEqual(result["blocked_reason"], "pending_entry_session")
        self.assertEqual(result["last"]["px"], 3.3)
        self.assertNotIn("entry", result)

    def test_in_range_gap_keeps_last_point_but_no_entry(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars()), ["AAA"])
        result = book.performance("AAA", "2026-06-28", through_last=True)
        self.assertIsNone(result["return"])
        self.assertEqual(result["blocked_reason"], "missing_entry_session")
        self.assertEqual(result["last"]["px"], 3.3)
        self.assertNotIn("entry", result)

    def test_entry_snap_anchors_at_signal_time(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars()), ["AAA"])
        # foundry: last session strictly before the actionable date
        before = book.performance(
            "AAA", "2026-06-29", through_last=True, entry_snap="before")
        self.assertEqual(before["entry"]["date"], "2026-06-26")
        self.assertAlmostEqual(before["return"], 0.1)
        # daily producers: their own session's close when it exists...
        on = book.performance(
            "AAA", "2026-06-26", through_last=True, entry_snap="on_or_before")
        self.assertEqual(on["entry"]["date"], "2026-06-26")
        # ...or the closest earlier close across an in-range gap
        gap = book.performance(
            "AAA", "2026-06-28", through_last=True, entry_snap="on_or_before")
        self.assertEqual(gap["entry"]["date"], "2026-06-26")
        # nothing precedes the signal
        none = book.performance(
            "AAA", "2026-06-25", through_last=True, entry_snap="before")
        self.assertEqual(none["blocked_reason"], "missing_entry_session")
        self.assertEqual(none["last"]["px"], 3.3)

    def test_unresolved_crossing_is_never_returned(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars(status="conflict", blocked=["act-1"])), ["AAA"])
        result = book.performance("AAA", "2026-06-25", sessions=2)
        self.assertIsNone(result["return"])
        self.assertEqual(result["blocked_reason"], "corporate_action_unresolved")
        self.assertEqual(result["blocked_action_ids"], ["act-1"])

    def test_observed_action_after_entry_is_context_without_blocking_same_basis_return(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars(status="observed", blocked=["act-1"])), ["AAA"])

        result = book.performance("AAA", "2026-06-26", sessions=1)

        self.assertAlmostEqual(result["return"], 0.1)
        self.assertIsNone(result["blocked_reason"])
        self.assertEqual(result["action_warning_ids"], [])
        self.assertEqual(result["action_context_ids"], ["act-1"])
        self.assertEqual(result["confirmation_status"], "observed")

    def test_observed_action_still_blocks_a_window_that_crosses_its_boundary(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars(status="observed", blocked=["act-1"])), ["AAA"])

        result = book.performance("AAA", "2026-06-25", sessions=2)

        self.assertIsNone(result["return"])
        self.assertEqual(result["blocked_reason"], "corporate_action_unresolved")
        self.assertEqual(result["action_warning_ids"], ["act-1"])

    def test_conflicting_action_remains_blocked_on_one_segment(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars(status="conflict", blocked=["act-1"])), ["AAA"])

        result = book.performance("AAA", "2026-06-26", sessions=1)

        self.assertIsNone(result["return"])
        self.assertEqual(result["blocked_reason"], "corporate_action_unresolved")

    def test_enrich_preserves_signal_price_but_uses_gateway_entry_and_exit(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars()), ["AAA"])

        class Store:
            all_dates = ["2026-06-25", "2026-06-26", "2026-06-29"]
            price_max_date = "2026-06-29"

            def performance(self, *args, **kwargs):
                return book.performance(*args, **kwargs)

            def series(self, ticker):
                return book.series(ticker)

        with patch("backend.metrics.STORE", Store()):
            row = enrich(
                {
                    "id": "x", "producer": "intrinsic", "date": "2026-06-25",
                    "ticker": "AAA", "decision": "BUY", "price": 3000.0,
                }
            )
        self.assertEqual(row["signal_price"], 3000.0)
        self.assertEqual(row["entry_px"], 3.0)
        self.assertEqual(row["entry_date"], "2026-06-25")
        self.assertAlmostEqual(row["ret_since"], 0.1)
        self.assertEqual(row["price_basis"], "confirmed_continuous")

    def test_enrich_does_not_overflag_observed_action_before_signal(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars(status="observed", blocked=["act-1"])), ["AAA"])
        store = self._store(book, ["2026-06-25", "2026-06-26", "2026-06-29"])

        with patch("backend.metrics.STORE", store):
            row = enrich({
                "id": "flagged", "producer": "lstm", "date": "2026-06-26",
                "ticker": "AAA", "decision": "BUY",
            })

        self.assertAlmostEqual(row["ret_since"], 0.1)
        self.assertEqual(row["status_perf"], "up")
        self.assertEqual(row["status_basis"], "since")
        self.assertFalse(row["has_action_warning"])
        self.assertEqual(row["action_warning_ids"], [])

    def _store(self, book, dates):
        class Store:
            all_dates = dates
            price_max_date = "2026-06-29"

            def performance(self, *args, **kwargs):
                return book.performance(*args, **kwargs)

            def series(self, ticker):
                return book.series(ticker)

        return Store()

    def test_enrich_anchors_foundry_entry_at_prior_close_and_captures_gap(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars()), ["AAA"])
        store = self._store(book, ["2026-06-25", "2026-06-26", "2026-06-29"])
        with patch("backend.metrics.STORE", store):
            row = enrich(
                {"id": "f", "producer": "foundry", "date": "2026-06-29",
                 "ticker": "AAA", "decision": "BUY"},
                spark=True,
            )
        # entry is the close before the actionable session; since includes the gap
        self.assertEqual(row["entry_date"], "2026-06-26")
        self.assertEqual(row["entry_px"], 3.0)
        self.assertAlmostEqual(row["ret_since"], 0.1)
        self.assertEqual(row["status_perf"], "up")
        # the actionable-session view is exposed alongside, pending until a
        # close after the actionable session exists
        self.assertEqual(row["actionable_entry_px"], 3.3)
        self.assertIsNone(row["ret_since_actionable"])
        self.assertFalse(row["px_stale"])
        self.assertEqual(row["spark"]["signal_i"], 1)

    def test_enrich_renders_trend_and_last_for_not_yet_traded_session(self):
        book = ContinuousPriceBook()
        book.load(Gateway(bars()), ["AAA"])
        store = self._store(
            book, ["2026-06-25", "2026-06-26", "2026-06-29", "2026-06-30"])
        with patch("backend.metrics.STORE", store):
            row = enrich(
                {"id": "f2", "producer": "foundry", "date": "2026-06-30",
                 "ticker": "AAA", "decision": "BUY"},
                spark=True,
            )
        # the 6/30 session hasn't traded: entry anchors at the 6/29 close,
        # last/trend render from ticker data, and the row is pending, not null
        self.assertEqual(row["entry_date"], "2026-06-29")
        self.assertEqual(row["entry_px"], 3.3)
        self.assertEqual(row["last_px"], 3.3)
        self.assertIsNone(row["ret_since"])
        self.assertIsNone(row["actionable_entry_px"])
        self.assertEqual(row["status_perf"], "pending")
        self.assertFalse(row["px_stale"])
        self.assertEqual(len(row["spark"]["px"]), 3)
        self.assertEqual(row["spark"]["signal_i"], 2)

    def test_analytics_counts_but_excludes_unresolved_buy_everywhere(self):
        class Producer:
            spec = {"metric": "metric", "hist_range": (0.0, 1.0), "hist_bins": 4}
            metric_values = [0.8]

            def run_rows(self):
                return [{"producer": "lstm", "date": "2026-06-25", "n_buy": 1, "status": "ok"}]

        class Store:
            all_dates = ["2026-06-25", "2026-06-29"]
            price_max_date = "2026-06-29"
            all_decisions = [
                {
                    "id": "bad", "producer": "lstm", "date": "2026-06-25",
                    "ticker": "AAA", "decision": "BUY", "metric": 0.8,
                    "signal_price": 105.0,
                }
            ]
            producers = {"lstm": Producer()}

            def performance(self, _ticker, _date, **_kwargs):
                return {
                    "return": None,
                    "blocked_reason": "corporate_action_unresolved",
                    "blocked_action_ids": ["act-1"],
                    "confirmation_status": "conflict",
                    "entry": {
                        "date": "2026-06-25", "px": 3.0,
                        "price_basis": "unresolved", "confirmation_status": "conflict",
                    },
                    "last": {"date": "2026-06-29", "px": 3.3},
                }

            def series(self, _ticker):
                return []

        with patch("backend.metrics.STORE", Store()):
            result = analytics()
        producer = result["by_producer"]["lstm"]
        self.assertEqual(producer["n_corporate_action_unresolved"], 1)
        self.assertEqual(producer["horizons"]["1d"]["n"], 0)
        self.assertEqual(producer["horizons"]["5d"]["n"], 0)
        self.assertEqual(result["cumulative"], [])
        self.assertEqual(result["scatter"], [])
        self.assertEqual(result["best"], [])
        self.assertEqual(result["worst"], [])

    def test_analytics_keeps_each_safe_horizon_on_a_flagged_signal(self):
        class Producer:
            spec = {
                "metric": "metric", "history_metric": "metric",
                "hist_range": (0.0, 1.0), "hist_bins": 4,
            }
            metric_values = [0.8]

            def run_rows(self):
                return [{"producer": "lstm", "date": "2026-06-25", "n_buy": 1, "status": "ok"}]

        row = {
            "id": "partial", "producer": "lstm", "date": "2026-06-25",
            "ticker": "AAA", "decision": "BUY", "metric": 0.8,
            "status_perf": "up", "status_basis": "1d",
            "ret_1d": 0.02, "ret_5d": None, "ret_20d": None,
            "ret_since": None, "blocked_return_reason": "corporate_action_unresolved",
            "has_action_warning": True, "action_warning_ids": ["act-1"],
        }
        store = type("Store", (), {"producers": {"lstm": Producer()}})()
        with (
            patch("backend.metrics.STORE", store),
            patch("backend.metrics.enriched_decisions", return_value=[row]),
        ):
            result = analytics()

        producer = result["by_producer"]["lstm"]
        self.assertEqual(producer["n_corporate_action_unresolved"], 1)
        self.assertEqual(producer["horizons"]["1d"]["n"], 1)
        self.assertEqual(producer["horizons"]["5d"]["n"], 0)
        self.assertEqual(len(result["cumulative"]), 1)


if __name__ == "__main__":
    unittest.main()
