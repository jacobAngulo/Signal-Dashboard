from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from backend import main


class DashboardApiUxTests(unittest.TestCase):
    def test_score_search_treats_user_text_as_literal(self):
        producer = SimpleNamespace(
            scores={"2026-07-20": pd.DataFrame([
                {"ticker": "A[B", "best_adj_prob": 0.3},
                {"ticker": "ABC", "best_adj_prob": 0.2},
            ])},
            spec={"history_metric": "best_adj_prob"},
            dates=["2026-07-20"],
        )
        store = SimpleNamespace(producers={"lstm": producer})
        with patch.object(main, "STORE", store):
            result = main.scores(
                "lstm", "2026-07-20", sort=None, dir="desc",
                limit=10, offset=0, q="[",
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["ticker"], "A[B")

    def test_signal_feed_filters_summarizes_and_pages_before_sparks(self):
        rows = [
            {
                "id": "a", "producer": "lstm", "date": "2026-07-20",
                "ticker": "AAA", "decision": "BUY", "metric": 0.3,
                "status_perf": "up", "ret_1d": 0.1, "ret_5d": 0.2,
                "ret_since": 0.25,
            },
            {
                "id": "b", "producer": "lstm", "date": "2026-07-19",
                "ticker": "BBB", "decision": "BUY", "metric": 0.2,
                "status_perf": "down", "ret_1d": -0.1, "ret_5d": -0.2,
                "ret_since": -0.25,
            },
        ]
        store = SimpleNamespace(producers={"lstm": object()})
        with (
            patch.object(main, "STORE", store),
            patch.object(main, "enriched_decisions", return_value=rows),
        ):
            result = main.signals(
                producer="lstm", ticker=None, q=None, date_from=None,
                date_to=None, status=None, min_metric=None, buys_only=True,
                spark=False, sort="date", dir="desc", limit=1, offset=0,
            )

        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["signals"]), 1)
        self.assertEqual(result["signals"][0]["ticker"], "AAA")
        self.assertEqual(result["summary"]["wr_5d"], 0.5)

    def test_score_only_ticker_has_a_valid_detail_page(self):
        producer = SimpleNamespace(
            history={"AACI": [{"date": "2026-07-20", "metric": None}]},
            dates=["2026-07-20"],
        )
        store = SimpleNamespace(
            producers={"lstm": producer}, prices={},
            series=lambda _ticker: [],
        )
        with (
            patch.object(main, "STORE", store),
            patch.object(main, "enriched_decisions", return_value=[]),
        ):
            result = main.ticker_view("aaci")

        self.assertEqual(result["ticker"], "AACI")
        self.assertEqual(result["last_scored"], "2026-07-20")
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["insights"]["status"], "available")

    def test_unresolved_ticker_keeps_descriptive_insights_available(self):
        series = [
            {
                "date": "2026-07-18", "px": 10.0,
                "confirmation_status": "confirmed", "blocked_action_ids": [],
            },
            {
                "date": "2026-07-19", "px": 11.0,
                "confirmation_status": "conflict", "blocked_action_ids": ["act-1"],
            },
        ]
        signals = [
            {
                "producer": "lstm", "date": "2026-07-18", "decision": "BUY",
                "blocked_return_reason": "corporate_action_unresolved",
            }
        ]

        result = main._ticker_insights(
            signals,
            series,
            {"lstm": [{"date": "2026-07-19", "metric": 0.31}]},
        )

        self.assertEqual(result["status"], "available")
        self.assertTrue(result["has_action_warning"])
        self.assertEqual(result["buy_count"], 1)
        self.assertEqual(result["latest_scores"]["lstm"]["metric"], 0.31)
        self.assertEqual(result["blocked_action_ids"], ["act-1"])
        self.assertEqual(result["action_boundary_count"], 1)
        self.assertEqual(result["performance_excluded_count"], 1)

    def test_intraday_chart_is_separate_from_daily_performance_book(self):
        bars = [{
            "ticker": "ALAB",
            "timestamp": "2026-07-27T19:15:00+00:00",
            "date": "2026-07-27",
            "open": 280.0,
            "high": 283.0,
            "low": 279.0,
            "close": 282.5,
            "volume": 1000,
            "confirmation_status": "confirmed",
            "blocked_action_ids": [],
        }]
        store = SimpleNamespace(
            ticker_index={"ALAB": {}},
            intraday_series=lambda *_args, **_kwargs: bars,
        )
        signals = [{
            "id": "s1", "producer": "lstm", "date": "2026-07-27",
            "ticker": "ALAB", "decision": "BUY",
            "created_at": "2026-07-27T19:18:00+00:00",
        }]
        with (
            patch.object(main, "STORE", store),
            patch.object(main, "enriched_decisions", return_value=signals),
        ):
            result = main.ticker_chart("alab", interval="5Min", window="1M")

        self.assertEqual(result["interval"], "5Min")
        self.assertEqual(result["window"], "1M")
        self.assertEqual(result["series"][0]["timestamp"], bars[0]["timestamp"])
        self.assertEqual(
            result["signals"][0]["chart_time"],
            "2026-07-27T19:18:00+00:00",
        )
        self.assertEqual(result["price_basis"], "dashboard_continuous_intraday")

    def test_intraday_window_must_fit_selected_bar_interval(self):
        store = SimpleNamespace(ticker_index={"ALAB": {}})
        with patch.object(main, "STORE", store):
            with self.assertRaises(main.HTTPException) as raised:
                main.ticker_chart("alab", interval="1Min", window="1M")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("at most 7 days", raised.exception.detail)

    def test_lstm_windows_use_duration_order_and_counts(self):
        scores = {
            "2026-07-20": pd.DataFrame([
                {"ticker": "DAY", "status": "buy_candidate", "best_horizon": "1d", "best_adj_prob": 0.2},
                {"ticker": "MON", "status": "buy_candidate", "best_horizon": "1m", "best_adj_prob": 0.3},
                {"ticker": "NOPE", "status": "no_buy", "best_horizon": "6m", "best_adj_prob": 0.1},
            ]),
            "2026-07-19": pd.DataFrame([
                {"ticker": "WEEK", "status": "buy_candidate", "best_horizon": "1w", "best_adj_prob": 0.4},
            ]),
        }
        decisions = [
            {"decision": "BUY", "date": "2026-07-20", "ticker": "MON", "horizon": "1m"},
            {"decision": "BUY", "date": "2026-07-19", "ticker": "WEEK", "horizon": "1w"},
        ]
        producer = SimpleNamespace(decisions=decisions, scores=scores)
        store = SimpleNamespace(producers={"lstm": producer})
        with patch.object(main, "STORE", store):
            result = main.lstm_windows()

        self.assertEqual(result["windows"], ["1d", "1w", "1m", "6m"])
        self.assertEqual(result["counts"], {"1d": 1, "1w": 1, "1m": 1, "6m": 0})
        self.assertEqual(result["scored_counts"]["6m"], 1)
        self.assertTrue(result["days"][0]["signals"]["1m"][0]["selected"])
        self.assertFalse(result["days"][0]["signals"]["1d"][0]["selected"])


if __name__ == "__main__":
    unittest.main()
