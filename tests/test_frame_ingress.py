"""Blank cells must not become NaN inside signal rows.

A CSV blank arrives from pandas as NaN, which is a float and is *truthy*, so
every `value or default` guard in the backend passes it through. TB-15 was the
visible form of that: an intrinsic WATCH row for BAND carried a NaN
`created_at`, a foundry row for the same ticker-day carried a real timestamp,
and the ticker page's `max()` tried to compare a float with a string.

The valuable tests here are `test_no_producer_row_carries_nan` and
`test_every_sortable_column_survives_mixed_types`. The rest pin the specific
regression. Those two walk every producer spec and every sortable column the
API exposes, so a producer or a column added next year is covered by a test
written today -- fixing the one field that broke would have left the next
blank cell to find its own way into a 500.
"""

import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from backend import main
from backend.frames import records, sort_key
from backend.main import _ticker_insights
from backend.store import PRODUCERS, ProducerData


def nan_fields(row):
    return {k: v for k, v in row.items()
            if isinstance(v, float) and math.isnan(v)}


class FrameIngressTests(unittest.TestCase):
    def test_records_replaces_missing_values_with_none(self):
        frame = pd.DataFrame([
            {"ticker": "AAA", "stamp": "2026-07-29T15:25:02", "metric": 0.4},
            {"ticker": "BBB", "stamp": None, "metric": None},
        ])

        rows = records(frame)

        self.assertEqual(rows[1]["stamp"], None)
        self.assertEqual(rows[1]["metric"], None)
        self.assertEqual(rows[0]["metric"], 0.4)
        self.assertEqual(nan_fields(rows[1]), {})

    def test_records_keeps_the_fast_path_honest(self):
        # A frame with no gaps skips the object copy; it must still agree.
        frame = pd.DataFrame([{"ticker": "AAA", "metric": 0.4}])
        self.assertEqual(records(frame), frame.to_dict("records"))
        self.assertEqual(records(pd.DataFrame()), [])

    def test_no_producer_row_carries_nan(self):
        """Every column blank, for every producer that reads files."""
        for name, spec in PRODUCERS.items():
            if not spec.get("scores_glob"):
                continue  # foundry reads DuckDB, not CSVs
            with self.subTest(producer=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                columns = {
                    "ticker": ["AAA", "BBB"],
                    spec["metric"]: [0.4, None],
                    spec["history_metric"]: [0.4, None],
                    spec["price_col"]: [10.0, None],
                    "decision": ["BUY", "BUY"],
                    "as_of_timestamp": ["2026-07-29T15:25:02", None],
                    "status": ["buy_candidate", None],
                }
                if spec.get("attention_col"):
                    columns[spec["attention_col"]] = [True, True]
                    columns[spec["attention_reason_col"]] = ["volume", None]
                frame = pd.DataFrame(columns)
                date = "2026-07-29"
                frame.to_csv(
                    root / spec["scores_glob"].replace("*", date), index=False)
                frame.to_csv(
                    root / spec["decision_glob"].replace("*", date), index=False)

                producer = ProducerData(name)
                producer.spec = copy.deepcopy(spec)
                producer.spec["dir"] = root
                producer.load()

                self.assertTrue(producer.decisions)
                for row in producer.decisions:
                    self.assertEqual(
                        nan_fields(row), {},
                        f"{name} row kept pandas NaN: {row.get('id')}")

    def test_sort_key_compares_across_types(self):
        values = ["2026-07-29", None, 0.4, float("nan"), True, "text"]
        # The assertion is only that this terminates instead of raising.
        self.assertEqual(len(sorted(values, key=sort_key)), len(values))
        self.assertEqual(max(["2026-07-28", "2026-07-29"], key=sort_key),
                         "2026-07-29")
        self.assertEqual(sort_key(None), sort_key(float("nan")))
        self.assertLess(sort_key(None), sort_key(0.0))

    def test_ticker_page_survives_a_missing_timestamp(self):
        """TB-15: same date, one row stamped, one row not."""
        signals = [
            {"date": "2026-07-29", "producer": "foundry", "decision": "WATCH",
             "created_at": "2026-07-29T11:45:39"},
            {"date": "2026-07-29", "producer": "intrinsic", "decision": "WATCH",
             "created_at": float("nan")},
            {"date": "2026-07-24", "producer": "intrinsic", "decision": "WATCH",
             "created_at": None},
        ]

        insights = _ticker_insights(signals, [], {})

        self.assertEqual(insights["latest_signal"]["date"], "2026-07-29")
        self.assertEqual(insights["producer_count"], 2)

    def test_every_sortable_column_survives_mixed_types(self):
        """The signals feed sorts on a user-supplied column."""
        rows = [
            {"id": "a", "producer": "lstm", "date": "2026-07-29",
             "ticker": "AAA", "decision": "BUY", "metric": 0.4,
             "status_perf": "up", "ret_1d": 0.1, "ret_5d": 0.2,
             "ret_20d": 0.3, "ret_since": 0.4},
            # Producers write these columns; two of them can disagree about
            # the type, and sorting must not be where that becomes a 500.
            # (Returns are computed here, not read from a file, so they stay
            # numeric -- missing or NaN is the most a caller can do to them.)
            {"id": "b", "producer": "intrinsic", "date": 20260729,
             "ticker": "BBB", "decision": "BUY", "metric": 0.5,
             "status_perf": 1, "ret_1d": None, "ret_5d": 0.2,
             "ret_20d": float("nan"), "ret_since": None},
        ]
        sortable = ["date", "ticker", "producer", "metric", "ret_1d", "ret_5d",
                    "ret_20d", "ret_since", "status_perf"]

        with patch.object(main, "enriched_decisions", return_value=rows), \
                patch.object(main, "enrich", side_effect=lambda row, **kw: row):
            for column in sortable:
                for direction in ("asc", "desc"):
                    with self.subTest(sort=column, dir=direction):
                        result = main.signals(
                            sort=column, dir=direction, limit=None, offset=0)
                        self.assertEqual(result["total"], 2)


if __name__ == "__main__":
    unittest.main()
