"""The vector lab's catalogue, predicates and bucketing.

`backend/lab.py` deliberately depends on nothing but the standard library so
these run anywhere, including the frontend box where the producers, the
gateway and DuckDB do not exist. The endpoint that wires it up is covered by
`test_auth_gate.py` (it walks the real route table) and by
`test_api_fixtures.py`; what needs its own tests is the arithmetic, because
every defect this module was written to fix was an arithmetic one that rendered
as a plausible-looking table.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import lab  # noqa: E402


def rows(*specs):
    """Minimal candidate rows: only the fields a test actually asserts on."""
    out = []
    for index, spec in enumerate(specs):
        row = {"id": f"r{index}", "ticker": spec.get("ticker", "AAA")}
        row.update(spec)
        out.append(row)
    return out


# ------------------------------------------------------------------ catalogue

def test_catalog_drops_constants_and_empties():
    """A field that never varies is not something you can group by.

    `producer` is "lstm" on every row and the attention columns are null across
    the whole published history; offering either as a control produces a
    one-bucket table or an empty one.
    """
    catalog = lab.build_catalog(rows(
        {"producer": "lstm", "attention_status": None, "horizon": "1d"},
        {"producer": "lstm", "attention_status": None, "horizon": "6m"},
    ))
    keys = {vector["key"] for vector in catalog}
    assert "horizon" in keys
    assert "producer" not in keys
    assert "attention_status" not in keys


def test_catalog_drops_identity_and_prose():
    catalog = lab.build_catalog(rows(
        {"exit_note": "window still open", "metric": 0.2, "adj_prob": 0.2,
         "release_sha256": "aaa"},
        {"exit_note": "window closed", "metric": 0.3, "adj_prob": 0.3,
         "release_sha256": "bbb"},
    ))
    keys = {vector["key"] for vector in catalog}
    assert "adj_prob" in keys
    assert "id" not in keys
    assert "exit_note" not in keys
    assert "release_sha256" not in keys
    # `metric` is `adj_prob` under a second name. Carrying both would put one
    # vector in the ranking twice and make it look corroborated.
    assert "metric" not in keys


def test_constant_boolean_is_not_a_vector():
    catalog = lab.build_catalog(rows(
        {"attention_candidate": True, "selected": True},
        {"attention_candidate": True, "selected": False},
    ))
    kinds = {vector["key"]: vector["kind"] for vector in catalog}
    assert kinds["selected"] == "bool"
    assert "attention_candidate" not in kinds


def test_boolean_is_never_numeric():
    """True is numerically 1, and a numeric two-value field quantiles to one
    meaningless bucket. Booleans have to classify as categorical."""
    catalog = lab.build_catalog(rows({"px_stale": True}, {"px_stale": False}))
    vector = next(v for v in catalog if v["key"] == "px_stale")
    assert vector["kind"] == "bool"
    assert vector["numeric"] is False


def test_mixed_type_column_is_categorical_not_numeric():
    """Two producers writing one column as text and as a number is the ingress
    hazard `frames.sort_key` exists for. Sampling would call this numeric and
    silently drop the odd row out of every bucket."""
    catalog = lab.build_catalog(rows(
        *[{"volume_ratio_20": i / 10} for i in range(30)],
        {"volume_ratio_20": "n/a"},
    ))
    vector = next(v for v in catalog if v["key"] == "volume_ratio_20")
    assert vector["kind"] == "category"


def test_outcome_derived_fields_are_groupable_but_not_scannable():
    catalog = lab.build_catalog(rows(
        {"exit_return": 0.1, "adj_prob": 0.2, "date": "2026-01-02"},
        {"exit_return": -0.1, "adj_prob": 0.3, "date": "2026-01-05"},
    ))
    by_key = {vector["key"]: vector for vector in catalog}
    assert by_key["adj_prob"]["scannable"] is True
    # `exit_return` predicts `ret_5d` perfectly and means nothing.
    assert by_key["exit_return"]["scannable"] is False
    assert by_key["exit_return"]["excluded_reason"]
    # A time axis wins the ranking on any market-wide move.
    assert by_key["date"]["scannable"] is False


# ------------------------------------------------------------------ bucketing

def test_few_distinct_values_bucket_by_value():
    """The regression this module exists for.

    Slicing a sorted list into equal-count chunks over four distinct session
    counts produced "126.00 - 126.00" next to "21.00 - 126.00": not a range,
    just an artifact of cutting at a tie.
    """
    data = rows(*([{"window_sessions": 126}] * 40),
                *([{"window_sessions": 21}] * 10),
                *([{"window_sessions": 1}] * 5))
    vector = next(v for v in lab.build_catalog(data) if v["key"] == "window_sessions")
    assert vector["kind"] == "discrete"
    labels = [label for label, _ in lab.bucketize(data, vector, buckets=5)]
    assert labels == ["1", "21", "126"]


def test_quantile_buckets_do_not_overlap_and_cover_every_row():
    data = rows(*[{"adj_prob": i / 1000} for i in range(1000)])
    vector = next(v for v in lab.build_catalog(data) if v["key"] == "adj_prob")
    buckets = lab.bucketize(data, vector, buckets=5)
    assert len(buckets) == 5
    assert sum(len(members) for _, members in buckets) == len(data)
    seen = set()
    for _, members in buckets:
        ids = {row["id"] for row in members}
        assert not (ids & seen), "a row landed in two buckets"
        seen |= ids


def test_ties_do_not_straddle_buckets():
    """Half the rows sharing one value yields fewer buckets, not two buckets
    with the same value in both."""
    data = rows(*([{"pred_std": 0.5}] * 60),
                *[{"pred_std": i / 100} for i in range(40)])
    vector = next(v for v in lab.build_catalog(data) if v["key"] == "pred_std")
    buckets = lab.bucketize(data, vector, buckets=5)
    for label, members in buckets:
        values = {row["pred_std"] for row in members}
        if len(values) == 1:
            # The tied value must live in exactly one bucket.
            elsewhere = [other for other, rest in buckets
                         if other != label and any(r["pred_std"] in values for r in rest)]
            assert not elsewhere
    assert sum(len(members) for _, members in buckets) == len(data)


def test_missing_values_get_their_own_bucket_last():
    data = rows({"volatility": 0.1}, {"volatility": None}, {"volatility": 0.9})
    vector = next(v for v in lab.build_catalog(data) if v["key"] == "volatility")
    buckets = lab.bucketize(data, vector, buckets=2)
    assert buckets[-1][0] == lab.NO_VALUE
    assert len(buckets[-1][1]) == 1


def test_wide_categorical_folds_its_tail():
    """289 tickers is not a table. The largest groups stay, the rest fold."""
    data = rows(*[{"ticker": f"T{i}"} for i in range(50)])
    vector = next(v for v in lab.build_catalog(data) if v["key"] == "ticker")
    buckets = lab.bucketize(data, vector, max_groups=10)
    assert len(buckets) == 11
    assert buckets[-1][0] == lab.OTHER
    assert sum(len(members) for _, members in buckets) == len(data)


# ----------------------------------------------------------------- predicates

@pytest.mark.parametrize("clause, field, op, value", [
    ("adj_prob:gte:0.22", "adj_prob", "gte", 0.22),
    ("horizon:in:1d|1w", "horizon", "in", ["1d", "1w"]),
    ("ret_5d:notnull", "ret_5d", "notnull", None),
    ("ticker:contains:av", "ticker", "contains", "av"),
])
def test_parse_predicate(clause, field, op, value):
    parsed = lab.parse_predicate(clause)
    assert (parsed["field"], parsed["op"], parsed["value"]) == (field, op, value)


@pytest.mark.parametrize("clause", [
    "adj_prob", "adj_prob:between:0.2", "adj_prob:gte", "horizon:in:",
])
def test_bad_predicates_raise(clause):
    with pytest.raises(lab.PredicateError):
        lab.parse_predicate(clause)


def test_numeric_comparison_is_not_a_string_comparison():
    """`adj_prob:gte:0.22` compared as text is true for "0.9" and false for
    "0.221", which is the wrong answer twice."""
    data = rows({"adj_prob": 0.9}, {"adj_prob": 0.221}, {"adj_prob": 0.2})
    kept = lab.apply_predicates(data, [lab.parse_predicate("adj_prob:gte:0.22")])
    assert sorted(row["adj_prob"] for row in kept) == [0.221, 0.9]


def test_missing_values_satisfy_no_comparison():
    """Otherwise "high probability" silently includes every row that has no
    probability at all."""
    data = rows({"adj_prob": 0.5}, {"adj_prob": None}, {"adj_prob": ""})
    assert len(lab.apply_predicates(data, [lab.parse_predicate("adj_prob:gte:0.1")])) == 1
    assert len(lab.apply_predicates(data, [lab.parse_predicate("adj_prob:lt:0.1")])) == 0
    assert len(lab.apply_predicates(data, [lab.parse_predicate("adj_prob:isnull")])) == 2


def test_predicates_compose():
    data = rows({"horizon": "1d", "adj_prob": 0.3},
                {"horizon": "1d", "adj_prob": 0.1},
                {"horizon": "6m", "adj_prob": 0.3})
    kept = lab.apply_predicates(data, [
        lab.parse_predicate("horizon:eq:1d"),
        lab.parse_predicate("adj_prob:gte:0.2"),
    ])
    assert len(kept) == 1


# ------------------------------------------------------------------ measuring

def test_group_reports_rows_and_measured_separately():
    """A bucket of 100 rows where 3 have a five-day return is 3 rows of
    evidence, and the table has to be able to say so."""
    data = rows(*([{"horizon": "6m", "ret_5d": None}] * 97),
                *([{"horizon": "6m", "ret_5d": 0.1}] * 3),
                # `horizon` has to vary or it is not a vector at all.
                {"horizon": "1d", "ret_5d": -0.2})
    vector = next(v for v in lab.build_catalog(data) if v["key"] == "horizon")
    groups = {g["label"]: g for g in lab.group(data, vector, "ret_5d")}
    assert groups["6m"]["n"] == 100
    assert groups["6m"]["measured"] == 3
    assert groups["6m"]["avg"] == pytest.approx(0.1)


def test_thin_buckets_are_not_scored():
    """One three-row bucket must not crown a vector."""
    data = rows(*([{"horizon": "6m", "ret_5d": 0.0}] * 100),
                *([{"horizon": "1d", "ret_5d": 5.0}] * 3))
    catalog = lab.build_catalog(data)
    strict = next(e for e in lab.analyze(data, catalog, "ret_5d", min_bucket=20)
                  if e["key"] == "horizon")
    assert strict["spread"] is None
    loose = lab.analyze(data, catalog, "ret_5d", min_bucket=3)
    assert loose[0]["key"] == "horizon"


def test_the_missing_bucket_is_never_the_finding():
    data = rows(*([{"volatility": None, "ret_5d": 0.5}] * 50),
                *[{"volatility": i / 100, "ret_5d": 0.0} for i in range(50)])
    catalog = lab.build_catalog(data)
    for entry in lab.analyze(data, catalog, "ret_5d", min_bucket=5):
        if entry["spread"] is None:
            continue
        assert entry["best_label"] != lab.NO_VALUE
        assert entry["worst_label"] != lab.NO_VALUE


def test_support_is_the_thinner_bucket():
    """A 40pp spread across two 25-row buckets is not the same finding as one
    across two 2,000-row buckets, and the spread alone cannot say which."""
    data = rows(*([{"horizon": "6m", "ret_5d": 0.0}] * 500),
                *([{"horizon": "1d", "ret_5d": 0.4}] * 25))
    catalog = lab.build_catalog(data)
    entry = next(e for e in lab.analyze(data, catalog, "ret_5d", min_bucket=20)
                 if e["key"] == "horizon")
    assert entry["support"] == 25


# -------------------------------------------------------------------- domains

def test_numeric_domain_clips_the_tail_but_keeps_the_range():
    """The track has to be aimable and the range has to stay honest.

    Signal close runs from half a cent to thousands. A full-range track puts
    every row but a handful inside one pixel; clipping the drawn body at p95
    fixes that, and `min`/`max` still report what is really there so the number
    inputs can reach past the track.
    """
    data = rows(*[{"close": i} for i in range(100)], {"close": 100000})
    catalog = lab.build_catalog(data)
    domain = lab.domains(data, catalog)["close"]
    assert domain["kind"] == "numeric"
    assert domain["max"] == 100000
    assert domain["clip_hi"] < 1000, "one outlier still owns the whole track"
    assert domain["above"] >= 1
    assert sum(domain["bins"]) + domain["above"] + domain["below"] == 101


def test_numeric_domain_counts_missing_separately():
    data = rows(*[{"volatility": i / 100} for i in range(50)],
                *([{"volatility": None}] * 7))
    catalog = lab.build_catalog(data)
    domain = lab.domains(data, catalog)["volatility"]
    assert domain["missing"] == 7
    assert sum(domain["bins"]) + domain["above"] + domain["below"] == 50


def test_date_vectors_get_bounds_not_one_chip_per_day():
    """Seventy-five trading days is not a chip list."""
    data = rows(*[{"date": f"2026-0{1 + i // 28}-{1 + i % 28:02d}"} for i in range(75)])
    catalog = lab.build_catalog(data)
    domain = lab.domains(data, catalog)["date"]
    assert domain["kind"] == "date"
    assert domain["min"] < domain["max"]
    assert "values" not in domain


def test_category_domain_counts_every_value():
    data = rows(*([{"horizon": "6m"}] * 30), *([{"horizon": "1d"}] * 5),
                *([{"horizon": None}] * 2))
    catalog = lab.build_catalog(data)
    domain = lab.domains(data, catalog)["horizon"]
    assert domain["kind"] == "category"
    assert [(v["value"], v["n"]) for v in domain["values"]] == [("6m", 30), ("1d", 5)]
    assert domain["missing"] == 2


def test_domains_are_stable_under_filtering():
    """The rail is drawn from the universe, not the slice.

    This is the property that makes a facet reversible: if the domain shrank to
    whatever the facet currently matched, dragging a handle inward would move
    the track under it and there would be no way back out.
    """
    data = rows(*[{"adj_prob": i / 100} for i in range(100)])
    catalog = lab.build_catalog(data)
    full = lab.domains(data, catalog)["adj_prob"]
    narrowed = lab.apply_predicates(data, [lab.parse_predicate("adj_prob:lte:0.2")])
    assert len(narrowed) < len(data)
    # `domains` is always called with the universe; calling it with a slice is
    # what this guards against, so assert the two really do differ.
    assert lab.domains(narrowed, catalog)["adj_prob"]["max"] < full["max"]


# ------------------------------------------------------------------- analyze

def test_analyze_covers_every_vector_and_ranks_the_scannable_first():
    data = rows(*[{"adj_prob": i / 100, "horizon": "6m" if i % 2 else "1d",
                   "exit_return": (i % 7) / 100, "ret_5d": (i % 5) / 100}
                  for i in range(200)])
    catalog = lab.build_catalog(data)
    entries = lab.analyze(data, catalog, "ret_5d", min_bucket=5)
    keys = [e["key"] for e in entries]
    # Every vector gets a card, including the ones kept out of the ranking.
    assert set(keys) == {v["key"] for v in catalog} - {"ret_5d"}
    scannable = [i for i, e in enumerate(entries) if e["scannable"]]
    context = [i for i, e in enumerate(entries) if not e["scannable"]]
    assert max(scannable) < min(context), "context vectors must sort last"


def test_analyze_never_buckets_the_outcome_by_itself():
    """The highest-return bucket has the highest return. Not a finding."""
    data = rows(*[{"ret_5d": i / 100, "adj_prob": 0.2 + i / 1000} for i in range(100)])
    catalog = lab.build_catalog(data)
    for outcome in ("ret_5d",):
        keys = [e["key"] for e in lab.analyze(data, catalog, outcome, min_bucket=5)]
        assert outcome not in keys
