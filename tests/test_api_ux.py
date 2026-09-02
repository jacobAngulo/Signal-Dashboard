import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from starlette.requests import Request

from backend import auth, config, main


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
        producer = SimpleNamespace(decisions=decisions, scores=scores,
                                   fingerprint="order-and-counts")
        store = SimpleNamespace(
            producers={"lstm": producer},
            price_generation=0,
            candidate_price_book=SimpleNamespace(points={}),
            candidate_price_load_error=None,
            _candidate_price_build_busy=lambda: False,
        )
        with patch.object(main, "STORE", store):
            result = main.lstm_windows(limit=None)

        self.assertEqual(result["windows"], ["1d", "1w", "1m", "6m"])
        self.assertEqual(result["counts"], {"1d": 1, "1w": 1, "1m": 1, "6m": 0})
        self.assertEqual(result["scored_counts"]["6m"], 1)
        # Per-day rows stay as aggregates; the candidates themselves are one
        # flat list so the UI can sort and group on any vector.
        self.assertEqual(result["days"][0]["candidate_counts"]["1m"], 1)
        self.assertEqual(result["days"][0]["scored"], 3)
        by_ticker = {row["ticker"]: row for row in result["candidates"]}
        self.assertEqual(set(by_ticker), {"DAY", "MON", "WEEK"})
        self.assertTrue(by_ticker["MON"]["selected"])
        self.assertFalse(by_ticker["DAY"]["selected"])
        self.assertNotIn("NOPE", by_ticker)

    def test_lstm_windows_expose_vectors_and_performance_fields(self):
        """The tab's whole point is slicing, so every candidate carries the
        model vectors and the forward returns, and the payload declares which
        columns are sliceable rather than leaving the UI to guess."""
        scores = {
            "2026-07-20": pd.DataFrame([{
                "ticker": "DAY", "status": "buy_candidate", "best_horizon": "1d",
                "best_adj_prob": 0.2, "best_pred_prob": 0.21, "best_pred_std": 0.03,
                "close": 12.5, "volatility": 0.44, "volume_ratio_20": 1.8,
                "attention_status": "surge", "attention_horizon_sessions": 3,
                "price_basis": "economic_value_per_initial_share",
            }]),
        }
        producer = SimpleNamespace(decisions=[], scores=scores,
                                   fingerprint="vectors-and-performance")
        store = SimpleNamespace(
            producers={"lstm": producer},
            price_generation=0,
            candidate_price_book=SimpleNamespace(points={}),
            candidate_price_load_error=None,
            _candidate_price_build_busy=lambda: False,
        )
        with patch.object(main, "STORE", store):
            result = main.lstm_windows(limit=None)

        row = result["candidates"][0]
        for key in ("volatility", "volume_ratio_20", "attention_status",
                    "attention_horizon_sessions", "price_basis", "pred_std"):
            self.assertIn(key, row, f"{key} must survive onto the candidate")
        self.assertEqual(row["volatility"], 0.44)
        self.assertEqual(row["attention_status"], "surge")
        # Enrichment ran even with no price coverage: the return keys exist and
        # are honestly empty rather than absent.
        for key in ("ret_1d", "ret_5d", "ret_20d", "ret_since", "last_px"):
            self.assertIn(key, row, f"{key} must be present even when blocked")
        self.assertIsNone(row["ret_1d"])
        keys = {vector["key"] for vector in result["vectors"]}
        self.assertIn("volatility", keys)
        self.assertIn("adj_prob", keys)
        self.assertEqual(result["price_tier"]["total"], 1)
        self.assertEqual(result["price_tier"]["covered"], 0)


class LstmSlicingTests(unittest.TestCase):
    """The tab exists to be sliced, so filtering, sorting, paging and grouping
    all have to happen over the whole candidate set rather than over whatever
    page the browser happens to be holding."""

    def _store(self, fingerprint):
        rows = []
        for i, (ticker, horizon, prob, vol) in enumerate([
            ("AAA", "1d", 0.90, 1.0), ("BBB", "1d", 0.70, 2.0),
            ("CCC", "1w", 0.50, 3.0), ("DDD", "1w", 0.30, 4.0),
            ("EEE", "6m", 0.10, 5.0),
        ]):
            rows.append({"ticker": ticker, "status": "buy_candidate",
                         "best_horizon": horizon, "best_adj_prob": prob,
                         "volume_ratio_20": vol, "close": 10.0 + i})
        producer = SimpleNamespace(
            decisions=[{"decision": "BUY", "date": "2026-07-20",
                        "ticker": "AAA", "horizon": "1d"}],
            scores={"2026-07-20": pd.DataFrame(rows)},
            fingerprint=fingerprint,
        )
        return SimpleNamespace(
            producers={"lstm": producer},
            price_generation=0,
            candidate_price_book=SimpleNamespace(points={}),
            candidate_price_load_error=None,
            _candidate_price_build_busy=lambda: False,
        )

    def test_filters_sort_and_page_run_over_the_whole_set(self):
        with patch.object(main, "STORE", self._store("slice-basic")):
            page = main.lstm_windows(sort="adj_prob", dir="desc", limit=2, offset=0)
            self.assertEqual(page["total"], 5)
            self.assertEqual([r["ticker"] for r in page["candidates"]], ["AAA", "BBB"])

            # Page two continues the same global ordering, not a re-sort of a page.
            two = main.lstm_windows(sort="adj_prob", dir="desc", limit=2, offset=2)
            self.assertEqual([r["ticker"] for r in two["candidates"]], ["CCC", "DDD"])

            asc = main.lstm_windows(sort="adj_prob", dir="asc", limit=1, offset=0)
            self.assertEqual(asc["candidates"][0]["ticker"], "EEE")

            filtered = main.lstm_windows(horizon="1w", limit=None)
            self.assertEqual(filtered["total"], 2)
            self.assertEqual({r["ticker"] for r in filtered["candidates"]}, {"CCC", "DDD"})

            floor = main.lstm_windows(min_prob=0.5, limit=None)
            self.assertEqual(floor["total"], 3)

            picks = main.lstm_windows(picks_only=True, limit=None)
            self.assertEqual([r["ticker"] for r in picks["candidates"]], ["AAA"])

            found = main.lstm_windows(q="cc", limit=None)
            self.assertEqual([r["ticker"] for r in found["candidates"]], ["CCC"])

    def test_groups_summarise_the_filtered_set_not_the_page(self):
        with patch.object(main, "STORE", self._store("slice-groups")):
            result = main.lstm_windows(group_by="horizon", limit=1, offset=0)
            self.assertEqual(len(result["candidates"]), 1)
            by_label = {g["label"]: g for g in result["groups"]}
            # Grouping saw all five candidates even though one row was returned.
            self.assertEqual(sum(g["n"] for g in result["groups"]), 5)
            self.assertEqual(by_label["1d"]["n"], 2)
            self.assertEqual(by_label["1d"]["picks"], 1)
            self.assertEqual(by_label["6m"]["n"], 1)

            # A numeric vector is cut into equal-count buckets, not raw values.
            numeric = main.lstm_windows(group_by="volume_ratio_20", limit=1, offset=0)
            self.assertEqual(sum(g["n"] for g in numeric["groups"]), 5)
            self.assertTrue(all("–" in g["label"] for g in numeric["groups"]))

            # An unknown vector falls back rather than returning nothing.
            unknown = main.lstm_windows(group_by="not_a_vector", limit=1, offset=0)
            self.assertEqual(unknown["group_by"], "horizon")

    def test_grouping_respects_the_active_filter(self):
        with patch.object(main, "STORE", self._store("slice-filtered-groups")):
            result = main.lstm_windows(horizon="1d", group_by="horizon", limit=None)
            self.assertEqual([g["label"] for g in result["groups"]], ["1d"])
            self.assertEqual(result["groups"][0]["n"], 2)


class AuthStatusTests(unittest.TestCase):
    """`/api/auth/status` proves Google credentials reached the process.

    Ops Console opens this after promoting a credential candidate, so it has to
    answer truthfully and it has to answer without ever putting the client
    secret in a response body.

    The endpoint moved from `main` to `auth` when the sign-in flow landed, and
    it now also reports who is signed in -- the credential assertions below are
    unchanged, because what must never leak did not change with it.
    """

    CLIENT_ID = "123456789-abcdefg.apps.googleusercontent.com"
    CLIENT_SECRET = "GOCSPX-notarealsecretvalue1234"

    def status(self, client_id, client_secret):
        with (
            patch.object(config, "GOOGLE_CLIENT_ID", client_id),
            patch.object(config, "GOOGLE_CLIENT_SECRET", client_secret),
        ):
            # No cookie, so this never opens the session file.
            return auth.auth_status(Request({"type": "http", "headers": []}))

    def test_reports_credentials_are_loaded(self):
        result = self.status(self.CLIENT_ID, self.CLIENT_SECRET)

        self.assertIs(result["google_client_configured"], True)
        self.assertEqual(result["client_id_suffix"], self.CLIENT_ID[-30:])
        self.assertIs(result["signed_in"], False)

    def test_never_returns_the_client_secret(self):
        body = json.dumps(self.status(self.CLIENT_ID, self.CLIENT_SECRET))

        self.assertNotIn(self.CLIENT_SECRET, body)
        # Not even a prefix long enough to be worth guessing from.
        self.assertNotIn(self.CLIENT_SECRET[:12], body)
        # The full client ID stays out too; only its tail is published.
        self.assertNotIn(self.CLIENT_ID, body)

    def test_reports_unconfigured_when_keys_are_empty(self):
        result = self.status("", "")

        self.assertIs(result["google_client_configured"], False)
        self.assertIsNone(result["client_id_suffix"])

    def test_a_half_provisioned_pair_is_not_configured(self):
        """An ID without a secret is unusable, so it must not read as ready."""
        result = self.status(self.CLIENT_ID, "")

        self.assertIs(result["google_client_configured"], False)


if __name__ == "__main__":
    unittest.main()
