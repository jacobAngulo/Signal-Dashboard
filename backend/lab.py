"""Free-form vector exploration over the LSTM candidate set.

`/api/lstm/windows` answers one fixed question well: of the sixteen vectors
somebody listed in `LSTM_VECTORS`, which separates five-day returns. That list
is a curation, the bucketing is fixed, the filters are a hardcoded handful of
query parameters, and the outcome measured is always `ret_5d`. Good page. Not a
place to ask a question nobody anticipated.

This module is the other half: every field the enriched rows actually carry
becomes a vector, filters are arbitrary predicates, the outcome is selectable,
and two vectors can be crossed against each other. It reads the same cached,
already-enriched candidate rows -- there is no second data path, no producer
access, and nothing here writes.

Three deliberate differences from the older scan, each of which was a visible
defect there:

*   Numeric vectors with few distinct values group by value rather than by
    quantile. Equal-count slicing over `window_sessions` (four distinct values)
    produced the bucket "126.00 - 126.00" next to "21.00 - 126.00", which is
    not a range so much as an artifact of slicing a sorted list at a tie.
*   Bucket edges are assigned by value, not by list position, so a value can
    land in exactly one bucket and labels cannot overlap.
*   Fields derived from the outcome being measured are marked unscannable
    rather than silently ranked. `exit_return` "predicts" `ret_5d` beautifully
    and means nothing; the catalog says so instead of letting the ranking imply
    a finding.
"""
from __future__ import annotations

import math
import re
from statistics import median

# ------------------------------------------------------------------ catalog

# Identity, provenance and prose. None of these describe a candidate in a way
# that could group it: an id is unique by construction, a hash identifies a run
# rather than a row, and a note is a sentence written for a human.
EXCLUDED_FIELDS = frozenset({
    "id", "detail_inline",
    # `metric` is `adj_prob` under another name -- carrying both would put the
    # same vector in the ranking twice and make it look corroborated.
    "metric",
    "as_of_timestamp",
})
EXCLUDED_SUFFIXES = ("_note", "_sha256", "_hash", "_basis_note")

# Fields that are downstream of the returns being measured. Ranking them tells
# you the arithmetic works, not that the model does. They stay groupable --
# "how did the closed ones do" is a real question -- but they are kept out of
# the ranked scan and flagged in the catalog.
OUTCOME_DERIVED = frozenset({
    "ret_1d", "ret_5d", "ret_20d", "ret_since", "ret_since_actionable",
    "exit_return", "exit_px", "exit_date", "exit_state", "exit_basis",
    "status_perf", "status_basis", "last_px", "last_date", "px_stale",
    "blocked_return_reason", "sessions_elapsed", "has_action_warning",
})

# A time axis, not something the model published about a candidate: it wins any
# ranking on a market-wide move, which says nothing about the model.
TIME_AXES = frozenset({"date", "entry_date", "as_of_close_date"})

# What can be measured. Every one of these is a forward return already computed
# by `enrich()`; the lab picks which one the buckets and the ranking use.
OUTCOMES = (
    {"key": "ret_1d", "label": "1-day return"},
    {"key": "ret_5d", "label": "5-day return"},
    {"key": "ret_20d", "label": "20-day return"},
    {"key": "ret_since", "label": "Return since signal"},
    {"key": "ret_since_actionable", "label": "Return since actionable session"},
    {"key": "exit_return", "label": "Return at model's own exit"},
)
OUTCOME_KEYS = frozenset(o["key"] for o in OUTCOMES)
DEFAULT_OUTCOME = "ret_5d"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Below this, a numeric field is grouped by its distinct values instead of cut
# into quantiles: four distinct session counts do not have five quantiles, and
# pretending otherwise is where the degenerate "126.00 - 126.00" bucket came
# from.
DISCRETE_MAX_DISTINCT = 12

# Name-shaped formatting hints. Cosmetic only -- nothing branches on kind
# except the bucket label.
_MONEY_HINTS = ("_px", "close", "price")
_PCT_HINTS = ("prob", "ret_", "_rate", "return")


def _num(value):
    """Float, or None for anything that is not a finite number.

    Booleans are rejected on purpose: `True` is numerically 1, and letting a
    boolean flag through as a numeric vector would quantile-bucket a two-value
    field into a single meaningless range.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _kind_for(key, values):
    """Classify one field from the values it actually holds.

    Sampling is not enough here. A column that is numeric for ten thousand rows
    and a string for one is exactly the ingress hazard `frames.sort_key` exists
    for, and treating it as numeric would drop that one row silently. So this
    requires every non-null value to be numeric before calling a field numeric.
    """
    non_null = [v for v in values if v is not None and v != ""]
    if not non_null:
        return None
    if all(isinstance(v, bool) for v in non_null):
        # A flag that is True on every row it appears on is not a vector.
        # `attention_candidate` is exactly that on this history, and offering
        # it would be a control with one bucket behind it.
        return "bool" if len(set(non_null)) > 1 else None
    numbers = [_num(v) for v in non_null]
    if all(n is not None for n in numbers):
        distinct = len({n for n in numbers})
        if distinct <= 1:
            return None
        if distinct <= DISCRETE_MAX_DISTINCT:
            return "discrete"
        lowered = key.lower()
        if any(hint in lowered for hint in _PCT_HINTS):
            return "pct"
        if any(hint in lowered for hint in _MONEY_HINTS):
            return "money"
        return "num"
    if len({str(v) for v in non_null}) <= 1:
        return None
    if all(isinstance(v, str) and _DATE_RE.match(v) for v in non_null):
        return "date"
    return "category"


def _label_for(key):
    return key.replace("_", " ").replace(" px", " price").capitalize()


def build_catalog(rows):
    """Every usable vector on these rows, typed by inspection.

    A field is a vector when it varies. Constants are dropped rather than
    listed as empty controls: `producer` is "lstm" on all twelve thousand rows,
    and offering it as something to group by would waste a click to show one
    bucket. Fields that are entirely null are dropped the same way -- the
    attention columns are null across this whole history, and the older page's
    answer to that was a dropdown entry that produced an empty table.
    """
    keys = set()
    for row in rows:
        keys.update(row)
    catalog = []
    for key in sorted(keys):
        if key in EXCLUDED_FIELDS or key.endswith(EXCLUDED_SUFFIXES):
            continue
        values = [row.get(key) for row in rows]
        kind = _kind_for(key, values)
        if kind is None:
            continue
        non_null = sum(1 for v in values if v is not None and v != "")
        catalog.append({
            "key": key,
            "label": _label_for(key),
            "kind": kind,
            "numeric": kind in ("num", "pct", "money", "discrete"),
            "n": non_null,
            "coverage": (non_null / len(rows)) if rows else 0.0,
            "distinct": len({str(v) for v in values if v is not None and v != ""}),
            "outcome": key in OUTCOME_KEYS,
            # Why a vector is not in the ranked scan, in the payload, so the UI
            # can say it rather than leaving a silent absence.
            "scannable": not (key in OUTCOME_DERIVED or key in TIME_AXES),
            "excluded_reason": (
                "derived from the returns being measured" if key in OUTCOME_DERIVED
                else "a time axis, not a property of the candidate" if key in TIME_AXES
                else None),
        })
    return catalog


# ----------------------------------------------------------------- filtering

OPS = ("gte", "lte", "gt", "lt", "eq", "ne", "in", "nin", "contains",
       "isnull", "notnull")


class PredicateError(ValueError):
    """A `where` clause the caller can fix, as opposed to a server fault."""


def parse_predicate(raw):
    """`field:op:value` -> a dict. `isnull`/`notnull` take no value.

    Values are split on `|` for `in`/`nin`, and coerced to float when they look
    numeric so `adj_prob:gte:0.22` compares as a number rather than as the
    string "0.22" -- which would be true for "0.9" and false for "0.221".
    """
    parts = str(raw).split(":", 2)
    if len(parts) < 2:
        raise PredicateError(
            f"{raw!r} is not a predicate. Expected field:op:value, "
            f"e.g. adj_prob:gte:0.22")
    field, op = parts[0].strip(), parts[1].strip().lower()
    if op not in OPS:
        raise PredicateError(f"unknown operator {op!r}. Known: {', '.join(OPS)}")
    if op in ("isnull", "notnull"):
        return {"field": field, "op": op, "value": None}
    if len(parts) < 3:
        raise PredicateError(f"operator {op!r} needs a value: {field}:{op}:...")
    raw_value = parts[2]
    if op in ("in", "nin"):
        value = [v.strip() for v in raw_value.split("|") if v.strip() != ""]
        if not value:
            raise PredicateError(f"{field}:{op} needs at least one value")
    else:
        number = _num(raw_value)
        value = number if number is not None else raw_value
    return {"field": field, "op": op, "value": value}


def _matches(row, predicate):
    field, op, want = predicate["field"], predicate["op"], predicate["value"]
    have = row.get(field)
    blank = have is None or have == ""
    if op == "isnull":
        return blank
    if op == "notnull":
        return not blank
    if blank:
        # A missing value satisfies no comparison. Letting it pass would make
        # "high probability" silently include every row that has no probability.
        return False
    if op in ("in", "nin"):
        hit = str(have).strip().lower() in {str(v).strip().lower() for v in want}
        return hit if op == "in" else not hit
    if op == "contains":
        return str(want).strip().lower() in str(have).strip().lower()
    if isinstance(want, float):
        number = _num(have)
        if number is None:
            return False
        return {
            "gte": number >= want, "lte": number <= want,
            "gt": number > want, "lt": number < want,
            "eq": number == want, "ne": number != want,
        }[op]
    left, right = str(have).strip().lower(), str(want).strip().lower()
    return {
        "gte": left >= right, "lte": left <= right,
        "gt": left > right, "lt": left < right,
        "eq": left == right, "ne": left != right,
    }[op]


def apply_predicates(rows, predicates):
    for predicate in predicates:
        rows = [row for row in rows if _matches(row, predicate)]
    return rows


# ----------------------------------------------------------------- bucketing

NO_VALUE = "(no value)"
OTHER = "(other)"


def _fmt_for(kind):
    if kind == "pct":
        return lambda v: f"{v * 100:.1f}%"
    if kind == "money":
        return lambda v: f"${v:,.2f}"
    if kind == "discrete":
        return lambda v: (f"{v:g}")
    return lambda v: f"{v:.3g}"


def bucketize(rows, vector, *, buckets=5, max_groups=20):
    """Split rows into labelled buckets along one vector.

    Returns `[(label, members), ...]`, missing-value bucket last. Numeric
    vectors are cut at quantile *edges* and assigned by value, so ties cannot
    straddle two buckets and every label describes the values it actually
    contains. Categorical vectors keep the largest `max_groups` and fold the
    tail into one, because a ticker vector on this data has 289 values and a
    289-row table is not an answer.
    """
    if vector is None:
        return []
    key, kind = vector["key"], vector["kind"]
    present, missing = [], []
    for row in rows:
        value = row.get(key)
        (missing if value is None or value == "" else present).append(row)

    out = []
    if kind in ("category", "date", "bool"):
        groups = {}
        for row in present:
            value = row.get(key)
            label = ("true" if value is True else "false" if value is False
                     else str(value))
            groups.setdefault(label, []).append(row)
        ordered = sorted(groups.items(), key=lambda item: -len(item[1]))
        if kind == "date":
            ordered = sorted(groups.items(), key=lambda item: item[0], reverse=True)
        if len(ordered) > max_groups:
            head, tail = ordered[:max_groups], ordered[max_groups:]
            out = list(head)
            out.append((OTHER, [row for _, members in tail for row in members]))
        else:
            out = list(ordered)
    elif kind == "discrete":
        fmt = _fmt_for(kind)
        groups = {}
        for row in present:
            groups.setdefault(_num(row.get(key)), []).append(row)
        out = [(fmt(value), members)
               for value, members in sorted(groups.items(), key=lambda i: i[0])]
    else:
        values = sorted(_num(row.get(key)) for row in present)
        fmt = _fmt_for(kind)
        # Quantile edges, deduplicated: a field where half the rows share one
        # value yields fewer buckets than asked for rather than empty ones.
        edges = sorted({values[int(len(values) * i / buckets)]
                        for i in range(1, buckets)}) if values else []
        assigned = [[] for _ in range(len(edges) + 1)]
        for row in present:
            value = _num(row.get(key))
            index = 0
            while index < len(edges) and value >= edges[index]:
                index += 1
            assigned[index].append(row)
        for members in assigned:
            if not members:
                continue
            local = [_num(row.get(key)) for row in members]
            lo, hi = min(local), max(local)
            label = fmt(lo) if lo == hi else f"{fmt(lo)} – {fmt(hi)}"
            out.append((label, members))
    if missing:
        out.append((NO_VALUE, missing))
    return out


# ------------------------------------------------------------------ measuring

def _measure(members, outcome):
    values = [_num(row.get(outcome)) for row in members]
    values = [v for v in values if v is not None]
    stats = {
        "n": len(members),
        "measured": len(values),
        "tickers": len({row.get("ticker") for row in members}),
        "picks": sum(1 for row in members if row.get("selected")),
        "avg": (sum(values) / len(values)) if values else None,
        "median": median(values) if values else None,
        "win_rate": (sum(1 for v in values if v > 0) / len(values)) if values else None,
        "best": max(values) if values else None,
        "worst": min(values) if values else None,
    }
    # Context columns, so a bucket can be read without re-running the query on
    # a different outcome.
    for other in ("ret_1d", "ret_5d", "ret_since", "exit_return"):
        vals = [_num(row.get(other)) for row in members]
        vals = [v for v in vals if v is not None]
        stats[other] = (sum(vals) / len(vals)) if vals else None
    return stats


def group(rows, vector, outcome, *, buckets=5, max_groups=20):
    return [{"key": label, "label": label, **_measure(members, outcome)}
            for label, members in bucketize(rows, vector, buckets=buckets,
                                            max_groups=max_groups)]


# ------------------------------------------------------------------- domains

# Bins across the clipped body of a numeric vector. Enough to show shape in a
# control a few hundred pixels wide; more would be noise at that size.
HIST_BINS = 24

# The track is drawn over the 1st-95th percentile, not the full range. Signal
# close runs from half a cent to $6,380; on a full-range track every row but a
# handful sits inside the leftmost pixel and the control cannot be aimed.
# Clipping the top at p95 costs the ability to *drag* a bound into the tail --
# the number inputs still reach it, and a handle parked at either end means
# unbounded, so the tail is included by default rather than cut off. The counts
# outside the clip are reported so the control can say what is out there
# instead of hiding it.
CLIP_LO, CLIP_HI = 0.01, 0.95


def _quantile(values, q):
    """Nearest-rank quantile over a pre-sorted list."""
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
    return values[index]


def domains(rows, catalog):
    """What each vector's control needs to draw itself.

    Computed over the whole universe rather than the filtered slice, and this
    is the important part: a facet whose own range collapsed every time you
    dragged it could not be dragged back. The rail stays fixed; only the
    counts move.
    """
    out = {}
    for vector in catalog:
        key = vector["key"]
        if vector["numeric"]:
            values = sorted(v for v in (_num(row.get(key)) for row in rows)
                            if v is not None)
            missing = len(rows) - len(values)
            if not values:
                continue
            lo, hi = values[0], values[-1]
            clip_lo = _quantile(values, CLIP_LO)
            clip_hi = _quantile(values, CLIP_HI)
            if clip_hi <= clip_lo:
                clip_lo, clip_hi = lo, hi
            width = (clip_hi - clip_lo) or 1.0
            bins = [0] * HIST_BINS
            below = above = 0
            for value in values:
                if value < clip_lo:
                    below += 1
                elif value > clip_hi:
                    above += 1
                else:
                    index = min(HIST_BINS - 1,
                                int((value - clip_lo) / width * HIST_BINS))
                    bins[index] += 1
            out[key] = {
                "kind": "numeric", "min": lo, "max": hi,
                "clip_lo": clip_lo, "clip_hi": clip_hi,
                "bins": bins, "below": below, "above": above,
                "missing": missing,
                # A sane typing granularity for the number inputs: three
                # significant figures across the visible body.
                "step": max(width / 1000, 1e-9),
            }
        elif vector["kind"] == "date":
            # Two bounds, not one chip per trading day. ISO dates compare
            # correctly as strings, so `gte`/`lte` work on them unchanged.
            values = sorted(str(row.get(key)) for row in rows
                            if row.get(key) not in (None, ""))
            missing = len(rows) - len(values)
            if not values:
                continue
            out[key] = {
                "kind": "date", "min": values[0], "max": values[-1],
                "distinct": len(set(values)), "missing": missing,
            }
        else:
            counts = {}
            missing = 0
            for row in rows:
                value = row.get(key)
                if value is None or value == "":
                    missing += 1
                    continue
                label = ("true" if value is True else "false" if value is False
                         else str(value))
                counts[label] = counts.get(label, 0) + 1
            values = sorted(counts.items(), key=lambda item: -item[1])
            out[key] = {
                "kind": "category",
                "values": [{"value": label, "n": n} for label, n in values],
                "missing": missing,
            }
    return out


# ------------------------------------------------------------------ analysis

def analyze(rows, catalog, outcome, *, buckets=5, min_bucket=20, max_groups=20):
    """Bucket every vector at once, and score how far its buckets land apart.

    The curated page groups by one vector at a time because it was built around
    a dropdown. Here the whole catalogue is bucketed in a single pass and the
    result is what the page renders -- which also means the ranking and the
    breakdowns can never disagree, since the ranking is computed from the very
    buckets shown underneath it.
    """
    out = []
    for vector in catalog:
        # Bucketing the outcome by itself is a tautology with a number on it:
        # the highest-return bucket has the highest return. Leave it out rather
        # than let it top the ranking.
        if vector["key"] == outcome:
            continue
        groups = group(rows, vector, outcome, buckets=buckets, max_groups=max_groups)
        usable = [g for g in groups
                  if g["measured"] >= min_bucket and g["avg"] is not None
                  and g["label"] not in (NO_VALUE, OTHER)]
        entry = {
            "key": vector["key"], "label": vector["label"], "kind": vector["kind"],
            "numeric": vector["numeric"], "scannable": vector["scannable"],
            "excluded_reason": vector["excluded_reason"],
            "groups": groups, "measured_buckets": len(usable),
            "spread": None, "support": 0,
            "best_label": None, "worst_label": None,
        }
        if len(usable) >= 2:
            best = max(usable, key=lambda g: g["avg"])
            worst = min(usable, key=lambda g: g["avg"])
            entry.update({
                "spread": best["avg"] - worst["avg"],
                "support": min(best["measured"], worst["measured"]),
                "best_label": best["label"], "worst_label": worst["label"],
            })
        out.append(entry)
    # Vectors that separate the outcome come first; ones that cannot be scored
    # at all sink below ones that were scored and came out flat. Vectors kept
    # out of the ranking sort last regardless -- they are context, not findings.
    out.sort(key=lambda v: (not v["scannable"], v["spread"] is None,
                            -(v["spread"] or 0)))
    return out
