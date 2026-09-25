import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import pandas as pd

from backend.store import (
    FOUNDRY_ATTENTION,
    PRODUCERS,
    FoundryData,
    ProducerData,
    _assign_foundry_attention,
    _score_attention_decisions,
)


class ProducerAttentionTests(unittest.TestCase):
    def test_blank_no_buy_sentinel_does_not_become_nan_ticker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame([{"ticker": "AAA", "discount_to_intrinsic": 0.1, "price": 10.0}]) \
                .to_csv(root / "intrinsic_scores_2026-07-10.csv", index=False)
            pd.DataFrame([{"ticker": None, "decision": "NO_BUY"}]) \
                .to_csv(root / "intrinsic_decision_2026-07-10.csv", index=False)
            producer = ProducerData("intrinsic")
            producer.spec = copy.deepcopy(PRODUCERS["intrinsic"])
            producer.spec["dir"] = root

            producer.load()

            self.assertEqual(producer.decisions, [])
            self.assertIn("AAA", producer.history)
            self.assertNotIn("NAN", producer.history)

    def test_score_attention_is_watch_and_does_not_replace_buy_contract(self):
        frame = pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "status": "no_buy",
                    "discount_to_intrinsic": 0.19,
                    "shadow_only_candidate": True,
                    "shadow_reason": "shadow band only",
                },
                {
                    "ticker": "BBB",
                    "status": "buy_candidate",
                    "discount_to_intrinsic": 0.25,
                    "shadow_only_candidate": False,
                },
            ]
        )

        rows = _score_attention_decisions(
            "intrinsic", "2026-07-10", frame, PRODUCERS["intrinsic"]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "WATCH")
        self.assertEqual(rows[0]["tier"], "intrinsic_shadow")
        self.assertEqual(rows[0]["ticker"], "AAA")

    def test_producer_load_merges_coverage_and_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd.DataFrame(
                [
                    {
                        "ticker": "AAA",
                        "status": "no_buy",
                        "discount_to_intrinsic": 0.19,
                        "price": 10.0,
                        "shadow_only_candidate": True,
                        "shadow_reason": "shadow band only",
                    }
                ]
            ).to_csv(root / "intrinsic_scores_2026-07-10.csv", index=False)
            (root / "intrinsic_coverage_2026-07-10.json").write_text(
                json.dumps(
                    {
                        "passed": True,
                        "universe_count": 1000,
                        "ready_count": 700,
                        "ready_fraction": 0.7,
                    }
                ),
                encoding="utf-8",
            )
            producer = ProducerData("intrinsic")
            producer.spec = copy.deepcopy(PRODUCERS["intrinsic"])
            producer.spec["dir"] = root

            producer.load()

            run = producer.run_rows()[0]
            self.assertEqual(run["n_attention"], 1)
            self.assertTrue(run["coverage_passed"])
            self.assertFalse(run["has_status"])
            self.assertIsNotNone(run["generated_at"])
            self.assertEqual(run["ready_count"], 700)
            self.assertEqual(producer.decisions[0]["decision"], "WATCH")

    def test_failed_coverage_without_status_becomes_failed_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage_path = root / "intrinsic_coverage_2026-07-21.json"
            coverage_path.write_text(
                json.dumps(
                    {
                        "passed": False,
                        "technical_failure": True,
                        "ready_count": 0,
                        "universe_count": 2047,
                        "error": (
                            "FundamentalsUnavailableError: EPS snapshot missing "
                            "for the session: /srv/data/intrinsic/artifacts/output"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            producer = ProducerData("intrinsic")
            producer.spec = copy.deepcopy(PRODUCERS["intrinsic"])
            producer.spec["dir"] = root

            producer.load()

            run = producer.run_rows()[0]
            expected_generated = datetime.fromtimestamp(
                coverage_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            self.assertEqual(run["status"], "failed")
            self.assertFalse(run["has_status"])
            self.assertFalse(run["coverage_passed"])
            self.assertEqual(run["generated_at"], expected_generated)
            self.assertEqual(
                run["failure_reason"],
                "FundamentalsUnavailableError: EPS snapshot missing for the session",
            )
            self.assertNotIn("2026-07-21", producer.status)

    def test_status_manifest_takes_precedence_over_coverage_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "premarket_status_2026-07-21.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "finished_at": "2026-07-21T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            (root / "intrinsic_coverage_2026-07-21.json").write_text(
                json.dumps({"passed": False, "technical_failure": True}),
                encoding="utf-8",
            )
            producer = ProducerData("intrinsic")
            producer.spec = copy.deepcopy(PRODUCERS["intrinsic"])
            producer.spec["dir"] = root

            producer.load()

            run = producer.run_rows()[0]
            self.assertEqual(run["status"], "ok")
            self.assertTrue(run["has_status"])
            self.assertEqual(run["generated_at"], "2026-07-21T12:00:00+00:00")
            self.assertIsNone(run["failure_reason"])
            self.assertIn("coverage", producer.status["2026-07-21"])

    def test_foundry_attention_uses_fixed_daily_budget(self):
        decisions = [
            {
                "date": "2026-07-10",
                "ticker": ticker,
                "event_type": event_type,
                "signal_score": score,
            }
            for ticker, event_type, score in (
                ("AAA", "other", 0.9),
                ("BBB", "earnings", 0.1),
                ("CCC", "mna", 0.8),
            )
        ]
        with patch.dict(FOUNDRY_ATTENTION, {"top_k": 2}, clear=False):
            ranked = _assign_foundry_attention(decisions)

        by_ticker = {row["ticker"]: row for row in ranked}
        self.assertEqual(by_ticker["BBB"]["attention_rank"], 1)
        self.assertTrue(by_ticker["CCC"]["attention_candidate"])
        self.assertFalse(by_ticker["AAA"]["attention_candidate"])


class FoundryCausalityTests(unittest.TestCase):
    def test_foundry_rows_are_bucketed_by_extraction_not_backfill_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "foundry.duckdb"
            con = duckdb.connect(str(db))
            con.execute(
                """
                CREATE TABLE raw_items (
                    id TEXT, source TEXT, title TEXT, body TEXT, url TEXT,
                    published_at TEXT, fetched_at TIMESTAMP
                );
                CREATE TABLE events (
                    item_id TEXT, model TEXT, prompt_version TEXT,
                    extracted_at TIMESTAMP, is_signal BOOLEAN, tickers TEXT,
                    unknown_tickers TEXT, in_universe BOOLEAN,
                    company_mentions TEXT, event_type TEXT, sentiment INTEGER,
                    confidence DOUBLE, novelty DOUBLE, time_sensitivity TEXT,
                    evidence_quote TEXT, why_it_matters TEXT,
                    source_quality DOUBLE, signal_score DOUBLE,
                    attempts INTEGER, latency_s DOUBLE
                );
                """
            )
            con.execute(
                "INSERT INTO raw_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    "item",
                    "sec_edgar",
                    "title",
                    "",
                    "https://example.test",
                    "2026-05-11",
                    datetime(2026, 7, 8, 16, 55),
                ],
            )
            con.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "item",
                    "test-model",
                    "v2",
                    datetime(2026, 7, 8, 17, 0),
                    True,
                    '["AAA"]',
                    "[]",
                    True,
                    "[]",
                    "earnings",
                    0,
                    0.8,
                    0.5,
                    "swing",
                    "quote",
                    "reason",
                    0.95,
                    0.38,
                    1,
                    0.1,
                ],
            )
            con.close()

            foundry = FoundryData()
            foundry.db = db
            with (
                patch("backend.store.FOUNDRY_MODEL", "test-model"),
                patch("backend.store.FOUNDRY_PROMPT", "v2"),
            ):
                foundry.load(("2026-05-11", "2026-07-08", "2026-07-09"))

            self.assertEqual(len(foundry.decisions), 1)
            row = foundry.decisions[0]
            self.assertEqual(row["event_date"], "2026-05-11")
            self.assertEqual(row["date"], "2026-07-08")
            self.assertEqual(row["as_of_source"], "foundry_extraction")
            self.assertTrue(row["attention_candidate"])


if __name__ == "__main__":
    unittest.main()
