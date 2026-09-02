"""Signal-Dashboard API: read-only analytics over LSTM, Intrinsic, and Foundry signals."""
import math
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from . import auth
from .admin_api import router as admin_router
from .feedback import router as feedback_router
from .config import (
    FOUNDRY_DB,
    HOST,
    PORT,
    PRICE_REFRESH_SECONDS,
)
from .frames import records, sort_key
from .metrics import analytics, enrich, enriched_decisions, _stats
from .store import STORE, clean

app = FastAPI(title="Signal Dashboard", docs_url="/api/docs", openapi_url="/api/openapi.json")

# In front of everything, including the static mount at the bottom of this file
# and the OpenAPI routes above. `auth.PUBLIC_PATHS` is the complete list of what
# it lets past unauthenticated; see the module docstring for why the check lives
# here rather than on each route.
app.middleware("http")(auth.require_session)
app.include_router(auth.router)
app.include_router(admin_router)
app.include_router(feedback_router)


def fresh():
    STORE.refresh()


SIGNAL_SUMMARY_FIELDS = (
    "id", "producer", "date", "ticker", "decision", "metric", "status_perf",
    "spark", "entry_px", "entry_date", "last_px", "last_date", "ret_1d",
    "ret_5d", "ret_20d", "ret_since", "ret_since_actionable",
    "actionable_entry_px", "created_at", "px_stale", "event_date",
    "published_at", "extracted_at", "as_of_timestamp", "as_of_source",
    "source", "n_grouped", "n_events", "gate_reason", "w_pos", "w_neg",
    "last_published_at", "event_type", "horizon", "blocked_return_reason",
    "has_action_warning", "action_warning_ids", "status_basis",
    # TB-46: per-producer holding window (Phase A) and native exit (Phase C).
    "window_label", "window_sessions", "window_basis", "window_note",
    "exit_basis", "exit_state", "exit_date", "exit_px", "exit_return",
    "sessions_elapsed", "exit_note",
    # TB-46: stop/target historical simulation (Phase D/E) -- present only
    # when a request asked for one (see `_apply_sim`).
    "sim_outcome", "sim_exit_date", "sim_return", "sim_sessions_held",
    "sim_ambiguous", "sim_blocked_reason",
)


def _signal_summary(row):
    """Stable, compact list contract; full raw fields live in /api/signal."""
    return {key: row.get(key) for key in SIGNAL_SUMMARY_FIELDS if key in row}


def _slice_summary(rows, sim=False):
    ret_1d = _stats([row.get("ret_1d") for row in rows])
    ret_5d = _stats([row.get("ret_5d") for row in rows])
    ret_since = _stats([row.get("ret_since") for row in rows])
    statuses = {}
    for row in rows:
        status = row.get("status_perf") or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
    out = {
        "n": len(rows),
        "wr_1d": ret_1d["win_rate"],
        "wr_5d": ret_5d["win_rate"],
        "avg_5d": ret_5d["avg"],
        "avg_since": ret_since["avg"],
        "statuses": statuses,
    }
    if sim:
        counts = {"target": 0, "stop": 0, "held": 0, "open": 0}
        returns = []
        n_blocked = 0
        for row in rows:
            outcome = row.get("sim_outcome")
            if outcome in counts:
                counts[outcome] += 1
            if row.get("sim_blocked_reason"):
                n_blocked += 1
            if row.get("sim_return") is not None:
                returns.append(row["sim_return"])
        resolved = counts["target"] + counts["stop"]
        out["sim"] = {
            "counts": counts,
            "hit_rate": (counts["target"] / resolved) if resolved else None,
            "avg_return": (sum(returns) / len(returns)) if returns else None,
            "n_blocked": n_blocked,
        }
    return out


def _simulate_signal(row, *, stop_pct, target_pct, exit_window, trailing):
    """Attach a stop/target simulation to one already-enriched signal row.

    Mutates and returns `row`. Anchors on the *raw* signal date with the same
    entry_snap rule `enrich()` uses (not the already-resolved `entry_date`,
    which would double-snap), so the simulated entry lands on the identical
    session as the entry price already shown for this row.
    """
    snap = "before" if row.get("producer") == "foundry" else "on_or_before"
    side = "short" if row.get("decision") == "SELL" else "long"
    result = STORE.simulate_exit(
        row["ticker"], row["date"],
        stop=stop_pct, target=target_pct, max_sessions=exit_window,
        side=side, entry_snap=snap, trailing=trailing,
    )
    row["sim_outcome"] = result.get("outcome")
    row["sim_exit_date"] = result.get("exit_date")
    row["sim_return"] = result.get("return")
    row["sim_sessions_held"] = result.get("sessions_held")
    row["sim_ambiguous"] = result.get("ambiguous")
    row["sim_blocked_reason"] = result.get("blocked_reason")
    return row


def _apply_sim(rows, *, stop_pct, target_pct, exit_window, trailing, sim_outcome):
    """Simulate a stop/target over every row when either threshold is given.

    No params supplied ⇒ zero extra work and no `sim_*` keys anywhere in the
    response -- byte-identical to a request that never mentions the feature.
    Simulates over the whole slice (before pagination) so a summary computed
    from it is honest, and optionally narrows to one outcome afterward.
    Returns `(rows, simulating)`.
    """
    simulating = stop_pct is not None or target_pct is not None
    if not simulating:
        return rows, False
    for row in rows:
        _simulate_signal(row, stop_pct=stop_pct, target_pct=target_pct,
                         exit_window=exit_window, trailing=trailing)
    if sim_outcome:
        rows = [row for row in rows if row.get("sim_outcome") == sim_outcome]
    return rows, True


def _ticker_insights(signals, series, history):
    """Descriptive ticker context that remains useful when returns are blocked.

    Corporate-action uncertainty must keep cross-boundary performance out of
    analytics, but it does not invalidate observed bars, model scores, or the
    fact that a producer emitted a signal.
    """
    buys = [row for row in signals if row.get("decision") == "BUY"]
    decisions = {}
    for row in signals:
        decision = row.get("decision") or "UNKNOWN"
        decisions[decision] = decisions.get(decision, 0) + 1

    unresolved = [
        point for point in series
        if point.get("blocked_action_ids")
        or point.get("confirmation_status") not in {
            "confirmed", "clear", "not_applicable",
        }
    ]
    action_ids = sorted({
        str(action_id)
        for point in unresolved
        for action_id in (point.get("blocked_action_ids") or [])
    })
    action_boundaries = []
    previous_signature = None
    for point in series:
        signature = (
            tuple(sorted(str(value) for value in (point.get("blocked_action_ids") or []))),
            point.get("continuity_segment"),
        )
        if signature != previous_signature and signature[0]:
            action_boundaries.append(point)
        previous_signature = signature
    latest_scores = {}
    for producer, rows in history.items():
        if not rows:
            continue
        latest = max(rows, key=lambda row: sort_key(row.get("date")))
        latest_scores[producer] = {
            "date": latest.get("date"),
            "metric": latest.get("metric"),
        }

    latest_signal = max(
        signals,
        key=lambda row: (sort_key(row.get("date")), sort_key(row.get("created_at"))),
        default=None,
    )
    return {
        "status": "available",
        "has_action_warning": bool(unresolved),
        "decision_counts": decisions,
        "buy_count": len(buys),
        "producer_count": len({row.get("producer") for row in signals}),
        "latest_signal": (
            {
                "date": latest_signal.get("date"),
                "producer": latest_signal.get("producer"),
                "decision": latest_signal.get("decision"),
            }
            if latest_signal else None
        ),
        "latest_scores": latest_scores,
        "price_bars": len(series),
        "price_from": series[0].get("date") if series else None,
        "price_through": series[-1].get("date") if series else None,
        "unresolved_bar_count": len(action_boundaries),
        "action_boundary_count": len(action_boundaries),
        "blocked_action_ids": action_ids,
        "performance_excluded_count": sum(
            1 for row in buys
            if row.get("blocked_return_reason") == "corporate_action_unresolved"
        ),
        "note": (
            "Corporate-action review flagged; only return windows that cross "
            "an uncertain boundary are excluded."
            if unresolved else None
        ),
    }


def _build_health_reporter():
    """The standard health envelope -- see /projects/DEPLOYMENT_STANDARD.md.

    The old payload reported `status: ok` unconditionally and put the
    interesting facts beside it, so a price-load failure was visible in the
    body while the status still said healthy. Those facts are now checks, and
    `price_load_error` makes the overall status `degraded` on its own.
    """
    from ops_kit import health as ops_health

    reporter = ops_health.HealthReporter("signal-dashboard")

    def prices() -> ops_health.Check:
        if STORE.price_load_error:
            return ops_health.Check(
                "prices", ops_health.DEGRADED, str(STORE.price_load_error)
            )
        building = (
            STORE._price_build_busy() if hasattr(STORE, "_price_build_busy") else False
        )
        count = len(STORE.prices)
        if building:
            return ops_health.Check(
                "prices", ops_health.OK, f"{count} tickers; rebuild in progress"
            )
        if not count:
            return ops_health.Check("prices", ops_health.DEGRADED, "no tickers loaded")
        return ops_health.Check("prices", ops_health.OK, f"{count} tickers")

    def foundry() -> ops_health.Check:
        """The dashboard reads Signal-Foundry's database directly, so its
        absence is a real degradation of this service, not someone else's
        problem."""
        if not FOUNDRY_DB.exists():
            return ops_health.Check(
                "foundry_db", ops_health.DEGRADED, f"{FOUNDRY_DB} is missing"
            )
        return ops_health.Check("foundry_db", ops_health.OK, str(FOUNDRY_DB))

    reporter.add_check("prices", prices)
    reporter.add_check("foundry_db", foundry)
    return reporter


HEALTH = _build_health_reporter()


@app.get("/api/health", dependencies=[Depends(fresh)])
def health():
    # Pre-standard consumers read these top-level keys, so they ride along in
    # `info` rather than disappearing.
    return HEALTH.payload(
        info={
            "price_tickers": len(STORE.prices),
            "price_load_error": STORE.price_load_error,
        }
    )


@app.get("/api/overview", dependencies=[Depends(fresh)])
def overview():
    out = {"producers": {}, "latest_date": None, "calendar": [], "recent": {}}
    for name, prod in STORE.producers.items():
        runs = prod.run_rows()
        latest = runs[-1] if runs else None
        all_buys = enriched_decisions(producer=name, buys_only=True)
        stats_5d = _stats([r.get("ret_5d") for r in all_buys])
        entry = {
            "latest_run": latest,
            "totals": {
                "days": len(runs),
                "signals": len(all_buys),
                "win_5d": stats_5d["win_rate"],
                "avg_5d": stats_5d["avg"],
                "n_measurable": stats_5d["n"],
            },
        }
        pipeline = getattr(prod, "pipeline", None)
        if pipeline:
            entry["pipeline"] = pipeline
            entry["totals"]["events"] = getattr(prod, "n_signal_events", 0)
        out["producers"][name] = entry
        out["calendar"].extend(runs)
        if latest and (out["latest_date"] is None or latest["date"] > out["latest_date"]):
            out["latest_date"] = latest["date"]

    latest_signals = enriched_decisions(buys_only=True, spark=True)
    latest_signals.sort(
        key=lambda r: (sort_key(r["date"]), sort_key(r.get("created_at")),
                       sort_key(r["producer"])),
        reverse=True)
    # Bursty event producers can emit many near-identical rows for one ticker
    # in one day (bot chatter reposts); collapse them here so a single story
    # can't crowd everything else out of the recent list.
    deduped, seen = [], {}
    for r in latest_signals:
        key = (r["producer"], r["ticker"], r["date"], r.get("decision"))
        if key in seen:
            seen[key]["n_grouped"] = seen[key].get("n_grouped", 1) + 1
            continue
        seen[key] = r
        deduped.append(r)
    out["latest_signals"] = [_signal_summary(row) for row in deduped[:12]]

    ranked = [r for r in latest_signals if r.get("ret_5d") is not None]
    ranked.sort(key=lambda r: r["ret_5d"])
    slim = lambda r: {k: r.get(k) for k in
                      ("producer", "date", "ticker", "ret_5d", "status_perf")}
    out["recent"] = {"best": [slim(r) for r in ranked[::-1][:4]],
                     "worst": [slim(r) for r in ranked[:4]]}
    return clean(out)


@app.get("/api/runs", dependencies=[Depends(fresh)])
def runs():
    rows = []
    for prod in STORE.producers.values():
        rows.extend(prod.run_rows())
    rows.sort(key=lambda r: (r["date"], r["producer"]), reverse=True)
    return clean({"runs": rows})


# The sliceable vector columns the LSTM tab exposes. Declared here rather than
# hardcoded in the frontend so a new model column reaches the UI's grouping and
# filter controls by being listed once. Provenance hashes are deliberately not
# vectors — they identify a run, they do not describe a candidate.
LSTM_VECTORS = (
    {"key": "date", "label": "Trading day", "kind": "category"},
    {"key": "horizon", "label": "Best horizon", "kind": "category"},
    {"key": "selected", "label": "Final daily pick", "kind": "category"},
    {"key": "adj_prob", "label": "Adjusted probability", "kind": "pct"},
    {"key": "pred_prob", "label": "Predicted probability", "kind": "pct"},
    {"key": "pred_std", "label": "Prediction std", "kind": "num"},
    {"key": "volatility", "label": "Volatility", "kind": "num"},
    {"key": "volume_ratio_20", "label": "Volume ratio (20d)", "kind": "num"},
    {"key": "close", "label": "Signal close", "kind": "money"},
    {"key": "attention_status", "label": "Attention status", "kind": "category"},
    {"key": "attention_horizon_sessions", "label": "Attention sessions", "kind": "num"},
    {"key": "price_basis", "label": "Price basis", "kind": "category"},
    {"key": "status_perf", "label": "Performance status", "kind": "category"},
    {"key": "exit_state", "label": "Exit state", "kind": "category"},
    {"key": "window_label", "label": "Model window", "kind": "category"},
    {"key": "window_sessions", "label": "Window length (sessions)", "kind": "num"},
)
LSTM_VECTOR_KINDS = {vector["key"]: vector["kind"] for vector in LSTM_VECTORS}

# Score-file columns carried through verbatim onto each candidate.
LSTM_PASSTHROUGH = (
    "volatility", "attention_candidate", "attention_status",
    "attention_horizon_sessions", "attention_reason", "price_basis",
    "continuity_segment", "as_of_close_date", "as_of_timestamp", "as_of_source",
)

LSTM_CANDIDATE_FIELDS = (
    "id", "producer", "date", "ticker", "decision", "status", "horizon",
    "adj_prob", "pred_prob", "pred_std", "metric", "close", "volume_ratio_20",
    "selected", "detail_inline",
    *LSTM_PASSTHROUGH,
    # Performance, from the candidate price tier (see store._book_for).
    "entry_px", "entry_date", "last_px", "last_date", "ret_1d", "ret_5d",
    "ret_20d", "ret_since", "ret_since_actionable", "status_perf", "px_stale",
    "blocked_return_reason", "has_action_warning", "status_basis",
    # The model's own holding window and the exit it implies. Computed in
    # enrich() for every row; a 1d/1w/1m candidate resolves inside this
    # history, a 6m one (126 sessions) stays open.
    "window_label", "window_sessions", "window_basis", "window_note",
    "exit_basis", "exit_state", "exit_date", "exit_px", "exit_return",
    "sessions_elapsed", "exit_note",
)

LSTM_SORTABLE = {
    "date", "ticker", "horizon", "adj_prob", "pred_prob", "pred_std",
    "volatility", "volume_ratio_20", "close", "entry_px", "last_px",
    "ret_1d", "ret_5d", "ret_20d", "ret_since", "status_perf",
    "attention_status", "attention_horizon_sessions",
    "exit_state", "exit_date", "exit_return", "window_sessions", "sessions_elapsed",
}

LSTM_BUCKETS = 5

# What "resolved" means: the signal has a real direction, as opposed to waiting
# on a session (pending), having no coverage (no_px), or having its window cut
# by an unresolved corporate action (return_limited).
RESOLVED_STATUSES = frozenset({"up", "down", "flat"})

# Kept out of the vector ranking. `date` is a time axis, not something the
# model published about a candidate — and it wins the ranking on market-wide
# moves, which says nothing about the model. `status_perf` is derived from the
# very returns being measured, so ranking it would be circular. Both remain
# available to group by; they just aren't scored as predictors.
SCAN_EXCLUDED = frozenset({"date", "status_perf"})

# Bucket labels that mean "this row had no value here", not a value.
EMPTY_BUCKET_LABELS = frozenset({"(no value)", "(none)"})

# Enriching every candidate costs a few seconds over the full history, and the
# inputs only move when the score files reload or a price book swaps. Cache on
# exactly that, so filtering and paging are cheap.
_LSTM_CACHE = {"key": None, "value": None}
_LSTM_CACHE_LOCK = threading.Lock()


def _lstm_candidate_set():
    """All enriched LSTM candidates plus the whole-history aggregates."""
    prod = STORE.producers["lstm"]
    key = (getattr(prod, "fingerprint", None), STORE.price_generation)
    with _LSTM_CACHE_LOCK:
        if _LSTM_CACHE["key"] == key and _LSTM_CACHE["value"] is not None:
            return _LSTM_CACHE["value"]

    windows = ["1d", "1w", "1m", "6m"]
    selected = {
        (row.get("date"), row.get("ticker"), row.get("horizon"))
        for row in prod.decisions
        if row.get("decision") == "BUY"
    }
    days = []
    candidates = []
    counts = {window: 0 for window in windows}
    scored_counts = {window: 0 for window in windows}

    for date in sorted(prod.scores, reverse=True):
        frame = prod.scores[date]
        best_horizon_counts = {window: 0 for window in windows}
        candidate_counts = {window: 0 for window in windows}
        if "ticker" in frame.columns and "best_horizon" in frame.columns:
            for index, row in enumerate(records(frame)):
                ticker_value = row.get("ticker")
                horizon_value = row.get("best_horizon")
                ticker = str(ticker_value).strip().upper() if ticker_value is not None else ""
                horizon = str(horizon_value).strip() if horizon_value is not None else ""
                if not ticker or horizon not in best_horizon_counts:
                    continue
                best_horizon_counts[horizon] += 1
                scored_counts[horizon] += 1
                if str(row.get("status") or "").strip().lower() != "buy_candidate":
                    continue
                candidate = {
                    "id": f"lstm-score:{date}:{ticker}:{index}",
                    "producer": "lstm",
                    "date": date,
                    "ticker": ticker,
                    "decision": "CANDIDATE",
                    "status": "buy_candidate",
                    "horizon": horizon,
                    "adj_prob": row.get("best_adj_prob"),
                    "pred_prob": row.get("best_pred_prob"),
                    "pred_std": row.get("best_pred_std"),
                    "metric": row.get("best_adj_prob"),
                    "close": row.get("close"),
                    "volume_ratio_20": row.get("volume_ratio_20"),
                    "selected": (date, ticker, horizon) in selected,
                    "detail_inline": True,
                    **{key_: row.get(key_) for key_ in LSTM_PASSTHROUGH},
                }
                # Candidates are would-be BUYs, so they get a real direction
                # rather than the inert `no_action` a non-BUY row would take.
                enriched = enrich(candidate, spark=False, directional=True)
                candidates.append(
                    {field: enriched.get(field) for field in LSTM_CANDIDATE_FIELDS
                     if field in enriched}
                )
                candidate_counts[horizon] += 1
                counts[horizon] += 1
        days.append({
            "date": date,
            "candidate_counts": candidate_counts,
            "best_horizon_counts": best_horizon_counts,
            "total": sum(candidate_counts.values()),
            "scored": sum(best_horizon_counts.values()),
        })

    value = {
        "windows": windows,
        "counts": counts,
        "scored_counts": scored_counts,
        "days": days,
        "candidates": candidates,
    }
    with _LSTM_CACHE_LOCK:
        _LSTM_CACHE["key"] = key
        _LSTM_CACHE["value"] = value
    return value


def _lstm_groups(rows, group_by):
    """Aggregate a filtered candidate set along one vector.

    Categorical vectors group on the value; numeric ones are cut into
    equal-count buckets, so a long tail (volume ratio, volatility) still yields
    comparable groups instead of one crowded bucket and four empty ones.
    """
    kind = LSTM_VECTOR_KINDS.get(group_by)
    if kind is None or not rows:
        return []

    def stats(label, members):
        ret_1d = _stats([row.get("ret_1d") for row in members])
        ret_5d = _stats([row.get("ret_5d") for row in members])
        ret_since = _stats([row.get("ret_since") for row in members])
        exit_ret = _stats([row.get("exit_return") for row in members])
        return {
            "key": label,
            "label": label,
            "n": len(members),
            "tickers": len({row.get("ticker") for row in members}),
            "picks": sum(1 for row in members if row.get("selected")),
            "ret_1d": ret_1d["avg"],
            "ret_5d": ret_5d["avg"],
            "ret_since": ret_since["avg"],
            "wr_5d": ret_5d["win_rate"],
            "closed": sum(1 for row in members if row.get("exit_state") == "closed"),
            "exit_return": exit_ret["avg"],
            "wr_exit": exit_ret["win_rate"],
        }

    if kind == "category":
        groups = {}
        for row in rows:
            raw = row.get(group_by)
            label = ("★ pick" if raw is True else "candidate" if raw is False
                     else "(none)" if raw in (None, "") else str(raw))
            groups.setdefault(label, []).append(row)
        return sorted((stats(label, members) for label, members in groups.items()),
                      key=lambda group: -group["n"])

    present, missing = [], []
    for row in rows:
        value = _num(row.get(group_by))
        (present if value is not None else missing).append(row)
    present.sort(key=lambda row: _num(row.get(group_by)))
    out = []
    if present:
        size = math.ceil(len(present) / LSTM_BUCKETS)
        fmt = (lambda v: f"{v * 100:.1f}%") if kind == "pct" else (
            (lambda v: f"${v:,.2f}") if kind == "money" else (lambda v: f"{v:.2f}"))
        for offset in range(0, len(present), size):
            members = present[offset:offset + size]
            lo = _num(members[0].get(group_by))
            hi = _num(members[-1].get(group_by))
            out.append(stats(f"{fmt(lo)} – {fmt(hi)}", members))
    if missing:
        out.append(stats("(no value)", missing))
    return out


def _lstm_vector_scan(rows):
    """Rank every vector by how much it actually separates outcomes.

    The question this page exists to answer is which of the model's published
    numbers is worth paying attention to, so rather than making the reader
    click through thirteen groupings one at a time, score them all: for each
    vector, the spread between its best and worst bucket's average 5-day
    return. A vector whose buckets all land in the same place is telling you
    nothing, and should sort to the bottom where it belongs.

    Buckets thinner than MIN_BUCKET are ignored for the spread so one
    three-row bucket cannot crown a vector.
    """
    MIN_BUCKET = 20
    scan = []
    for vector in LSTM_VECTORS:
        if vector["key"] in SCAN_EXCLUDED:
            continue
        groups = _lstm_groups(rows, vector["key"])
        # The missing-value bucket is not a value of the vector — letting it
        # win "best bucket" would report absent data as the finding.
        usable = [g for g in groups
                  if g["n"] >= MIN_BUCKET and g["ret_5d"] is not None
                  and g["label"] not in EMPTY_BUCKET_LABELS]
        # One bucket cannot separate anything; a vector that produces only the
        # missing-value bucket (attention fields are null across this history)
        # is noise in a ranked list.
        if len(usable) < 2:
            continue
        best = max(usable, key=lambda g: g["ret_5d"])
        worst = min(usable, key=lambda g: g["ret_5d"])
        scan.append({
            "key": vector["key"],
            "label": vector["label"],
            "buckets": len(groups),
            "measured": len(usable),
            "best_label": best["label"],
            "best_ret_5d": best["ret_5d"],
            "best_n": best["n"],
            "worst_label": worst["label"],
            "worst_ret_5d": worst["ret_5d"],
            "worst_n": worst["n"],
            "spread": best["ret_5d"] - worst["ret_5d"],
        })
    # Vectors with no measurable spread sort last rather than sorting as zero.
    scan.sort(key=lambda v: (v["spread"] is None, -(v["spread"] or 0)))
    return scan


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@app.get("/api/lstm/windows", dependencies=[Depends(fresh)])
def lstm_windows(date_from: str = None, date_to: str = None,
                 horizon: str = None, q: str = None,
                 attention_status: str = None, status_perf: str = None,
                 min_prob: float = None, min_price: float = None,
                 picks_only: bool = False, resolved_only: bool = False,
                 group_by: str = "horizon",
                 sort: str = "date", dir: Literal["asc", "desc"] = "desc",
                 limit: int | None = Query(100, ge=1, le=500),
                 offset: int = Query(0, ge=0)):
    """Published LSTM candidates with their model vectors and performance.

    Daily decision files contain one global winner. Score files contain the
    wider above-threshold candidate universe, but deliberately persist only
    each ticker's best of the four model heads. This endpoint exposes all of
    that published evidence without inventing the discarded head values.

    Filtering, sorting and grouping happen here rather than in the browser: the
    full enriched history is ~12k candidates and several megabytes of JSON, so
    the client gets one page of rows plus aggregates computed over the whole
    filtered set. Forward returns come from the slower candidate price tier and
    can lag the decision universe's returns by up to
    CANDIDATE_PRICE_REFRESH_SECONDS — `price_tier` reports that plainly rather
    than letting a half-built book read as a flat set of missing returns.
    """
    base = _lstm_candidate_set()
    rows = base["candidates"]
    if date_from:
        rows = [row for row in rows if row["date"] >= date_from]
    if date_to:
        rows = [row for row in rows if row["date"] <= date_to]
    if horizon:
        rows = [row for row in rows if row.get("horizon") == horizon]
    if q:
        query = q.strip().upper()
        rows = [row for row in rows if query in row["ticker"]]
    if attention_status:
        rows = [row for row in rows if row.get("attention_status") == attention_status]
    if status_perf:
        rows = [row for row in rows if row.get("status_perf") == status_perf]
    if min_prob is not None:
        rows = [row for row in rows
                if _num(row.get("adj_prob")) is not None
                and _num(row.get("adj_prob")) >= min_prob]
    if min_price is not None:
        rows = [row for row in rows
                if _num(row.get("close")) is not None
                and _num(row.get("close")) >= min_price]
    if picks_only:
        rows = [row for row in rows if row.get("selected")]
    if resolved_only:
        rows = [row for row in rows if row.get("status_perf") in RESOLVED_STATUSES]

    sort = sort if sort in LSTM_SORTABLE else "date"
    present = [row for row in rows if row.get(sort) is not None]
    missing = [row for row in rows if row.get(sort) is None]
    present.sort(key=lambda row: sort_key(row[sort]), reverse=(dir == "desc"))
    ordered = present + missing
    total = len(ordered)
    page = ordered if limit is None else ordered[offset:offset + limit]

    covered = sum(
        1 for row in rows
        if row.get("blocked_return_reason") != "no_gateway_price_coverage"
    )
    return clean({
        "windows": base["windows"],
        "counts": base["counts"],
        "scored_counts": base["scored_counts"],
        "days": base["days"],
        "candidates": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "sort": sort,
        "dir": dir,
        "vectors": [dict(vector) for vector in LSTM_VECTORS],
        "group_by": group_by if group_by in LSTM_VECTOR_KINDS else "horizon",
        "groups": _lstm_groups(rows, group_by if group_by in LSTM_VECTOR_KINDS else "horizon"),
        "vector_scan": _lstm_vector_scan(rows),
        "summary": _slice_summary(rows),
        "facets": {
            "dates": sorted({row["date"] for row in base["candidates"]}, reverse=True),
            "attention_status": sorted({
                row["attention_status"] for row in base["candidates"]
                if row.get("attention_status")
            }),
            "status_perf": sorted({
                row["status_perf"] for row in base["candidates"]
                if row.get("status_perf")
            }),
        },
        "price_tier": {
            "tickers": len(STORE.candidate_price_book.points),
            "covered": covered,
            "total": len(rows),
            "building": STORE._candidate_price_build_busy(),
            "error": STORE.candidate_price_load_error,
        },
        "contract": "best_horizon_per_ticker",
    })


@app.get("/api/day/{date}", dependencies=[Depends(fresh)])
def day(date: str):
    all_dates = STORE.all_dates
    try:
        i = all_dates.index(date)
        prev_d = all_dates[i - 1] if i > 0 else None
        next_d = all_dates[i + 1] if i + 1 < len(all_dates) else None
    except ValueError:
        prev_d = next((d for d in reversed(all_dates) if d < date), None)
        next_d = next((d for d in all_dates if d > date), None)

    out = {"date": date, "prev": prev_d, "next": next_d, "producers": {}}
    for name, prod in STORE.producers.items():
        run = next((r for r in prod.run_rows() if r["date"] == date), None)
        df = prod.scores.get(date)
        top = []
        if df is not None and len(df):
            metric = prod.spec["history_metric"]
            if metric in df.columns:
                top = records(
                    df.sort_values(metric, ascending=False, na_position="last").head(12))
        decisions = enriched_decisions(producer=name, date_from=date,
                                       date_to=date, spark=False)
        decision_rank = {"BUY": 0, "SELL": 1, "WATCH": 2}
        decisions.sort(key=lambda row: (
            decision_rank.get(row.get("decision"), 3),
            -float(row.get("metric") or 0),
            row.get("ticker") or "",
        ))
        visible = [
            _signal_summary(enrich(row, spark=True)) for row in decisions[:75]
        ]
        out["producers"][name] = {
            "run": run,
            "status_raw": prod.status.get(date),
            "decisions": visible,
            "n_decisions_total": len(decisions),
            "decisions_truncated": len(decisions) > len(visible),
            "n_scores": len(df) if df is not None else 0,
            "scores_available": df is not None,
            "top_scores": top,
            "metric_col": prod.spec["history_metric"],
        }
    return clean(out)


@app.get("/api/scores/{producer}/{date}", dependencies=[Depends(fresh)])
def scores(producer: str, date: str, sort: str = None,
           dir: Literal["asc", "desc"] = "desc",
           limit: int = Query(100, ge=1, le=500),
           offset: int = Query(0, ge=0), q: str = None):
    prod = STORE.producers.get(producer)
    if prod is None:
        raise HTTPException(404, f"unknown producer {producer}")
    df = prod.scores.get(date)
    if df is None:
        raise HTTPException(404, f"no scores for {producer} on {date}")
    if q and "ticker" in df.columns:
        df = df[df["ticker"].astype(str).str.upper().str.contains(
            q.upper(), na=False, regex=False,
        )]
    sort = sort or prod.spec["history_metric"]
    if sort in df.columns:
        df = df.sort_values(sort, ascending=(dir == "asc"), na_position="last")
    total = len(df)
    page = df.iloc[offset:offset + min(limit, 500)]
    return clean({
        "producer": producer, "date": date, "total": total,
        "columns": list(df.columns),
        "rows": records(page),
        "dates": prod.dates,
    })


@app.get("/api/signals", dependencies=[Depends(fresh)])
def signals(producer: str = None, ticker: str = None, q: str = None,
            date_from: str = None, date_to: str = None,
            status: str = None, min_metric: float = None,
            buys_only: bool = True, spark: bool = False,
            sort: str = "date", dir: Literal["asc", "desc"] = "desc",
            limit: int | None = Query(None, ge=1, le=250),
            offset: int = Query(0, ge=0),
            stop_pct: Annotated[float | None, Query(gt=0, lt=1)] = None,
            target_pct: Annotated[float | None, Query(gt=0, lt=5)] = None,
            exit_window: Annotated[int, Query(ge=1, le=252)] = 20,
            trailing: bool = False,
            sim_outcome: str = None):
    if producer and producer not in STORE.producers:
        raise HTTPException(404, f"unknown producer {producer}")
    rows = enriched_decisions(producer, date_from, date_to, ticker,
                              buys_only, spark=False)
    if q:
        query = q.strip().upper()
        rows = [row for row in rows if query in (row.get("ticker") or "").upper()]
    if status:
        rows = [
            row for row in rows
            if (
                row.get("has_action_warning")
                if status == "corporate_action_unresolved"
                else row.get("status_perf") == status
            )
        ]
    if min_metric is not None:
        rows = [row for row in rows
                if row.get("metric") is not None and row["metric"] >= min_metric]

    # Only when asked, and over the full filtered slice (before pagination)
    # so both the page and the summary reflect everything the filters
    # matched, not just the one page a browser happens to render.
    rows, simulating = _apply_sim(
        rows, stop_pct=stop_pct, target_pct=target_pct,
        exit_window=exit_window, trailing=trailing, sim_outcome=sim_outcome,
    )

    sortable = {"date", "ticker", "producer", "metric", "ret_1d", "ret_5d",
                "ret_20d", "ret_since", "status_perf"}
    sort = sort if sort in sortable else "date"
    present = [row for row in rows if row.get(sort) is not None]
    missing = [row for row in rows if row.get(sort) is None]
    present.sort(key=lambda row: sort_key(row[sort]), reverse=(dir == "desc"))
    rows = present + missing
    total = len(rows)
    page = rows if limit is None else rows[offset:offset + limit]
    if spark:
        # `enrich` copies every existing key of the row it's given (including
        # the sim_* keys just attached above) before recomputing its own
        # fields, so the simulation survives this second pass untouched.
        page = [enrich(row, spark=True) for row in page]
    return clean({
        "signals": [_signal_summary(row) for row in page],
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": _slice_summary(rows, sim=simulating),
    })


@app.get("/api/signal", dependencies=[Depends(fresh)])
def signal_detail(id: str):
    row = next((row for row in STORE.all_decisions if row.get("id") == id), None)
    if row is None:
        raise HTTPException(404, "signal not found")
    return clean({"signal": enrich(row, spark=False)})


INTRADAY_WINDOWS = {
    "1Min": 7,
    "5Min": 31,
    "15Min": 93,
    "1Hour": 366,
}

CHART_WINDOWS = {
    "1D": 1,
    "5D": 5,
    "1M": 31,
    "3M": 93,
    "6M": 186,
    "1Y": 366,
}


@app.get("/api/ticker/{ticker}/chart", dependencies=[Depends(fresh)])
def ticker_chart(
    ticker: str,
    interval: Literal["1Min", "5Min", "15Min", "1Hour"] = "5Min",
    window: Literal["1D", "5D", "1M", "3M", "6M", "1Y"] = "5D",
):
    """Recent policy-transformed intraday bars for an open ticker page."""
    t = ticker.upper()
    if t not in getattr(STORE, "ticker_index", {}):
        raise HTTPException(404, f"no data for {t}")
    now = datetime.now(timezone.utc)
    window_days = CHART_WINDOWS[window]
    if window_days > INTRADAY_WINDOWS[interval]:
        raise HTTPException(
            422,
            f"{interval} supports at most {INTRADAY_WINDOWS[interval]} days",
        )
    start = now - timedelta(days=window_days)
    try:
        series = STORE.intraday_series(
            t,
            timeframe=interval,
            start=start.isoformat(),
            end=now.isoformat(),
        )
    except Exception as exc:
        raise HTTPException(502, f"intraday data unavailable: {exc}") from exc
    signals = enriched_decisions(ticker=t, buys_only=False)
    chart_signals = []
    for row in signals:
        summary = _signal_summary(row)
        summary["chart_time"] = next(
            (
                row.get(key)
                for key in (
                    "created_at", "extracted_at", "published_at",
                    "as_of_timestamp",
                )
                if row.get(key)
            ),
            None,
        )
        chart_signals.append(summary)
    return clean({
        "ticker": t,
        "interval": interval,
        "window": window,
        "series": series,
        "signals": chart_signals,
        "as_of": series[-1].get("timestamp") if series else None,
        "source": "alpaca_iex_raw",
        "price_basis": "dashboard_continuous_intraday",
    })


@app.get("/api/ticker/{ticker}", dependencies=[Depends(fresh)])
def ticker_view(ticker: str,
                stop_pct: Annotated[float | None, Query(gt=0, lt=1)] = None,
                target_pct: Annotated[float | None, Query(gt=0, lt=5)] = None,
                exit_window: Annotated[int, Query(ge=1, le=252)] = 20,
                trailing: bool = False,
                sim_outcome: str = None):
    t = ticker.upper()
    sigs = enriched_decisions(ticker=t, buys_only=False)
    history = {name: prod.history.get(t, [])
               for name, prod in STORE.producers.items()}
    if not sigs and t not in STORE.prices and not any(history.values()):
        raise HTTPException(404, f"no data for {t}")
    # Same "only when asked" rule as /api/signals, so the ticker page can show
    # the identical simulated exits for this one ticker.
    sigs, _ = _apply_sim(
        sigs, stop_pct=stop_pct, target_pct=target_pct,
        exit_window=exit_window, trailing=trailing, sim_outcome=sim_outcome,
    )
    buys = [s for s in sigs if s.get("decision") == "BUY"]
    series = STORE.series(t)
    scored_dates = []
    for rows in history.values():
        scored_dates.extend(h["date"] for h in rows)
    relevant_latest_runs = [
        prod.dates[-1]
        for name, prod in STORE.producers.items()
        if name != "foundry" and history.get(name) and getattr(prod, "dates", None)
    ]
    return clean({
        "ticker": t,
        "signals": [_signal_summary(row) for row in
                    sorted(sigs, key=lambda r: sort_key(r["date"]), reverse=True)],
        "series": series,
        "history": history,
        "insights": _ticker_insights(sigs, series, history),
        "price_as_of": series[-1]["date"] if series else None,
        "price_build_running": (
            STORE._price_build_busy()
            if hasattr(STORE, "_price_build_busy") else False
        ),
        "price_refresh_seconds": PRICE_REFRESH_SECONDS,
        "last_scored": max(scored_dates, default=None),
        # Compare a ticker only with producers that score it. Foundry can have
        # a next-session event bucket, but that does not make a daily-model
        # ticker stale one day early.
        "latest_run": max(relevant_latest_runs, default=None),
        "stats": {
            "n_signals": len(buys),
            "first_signal": min((s["date"] for s in buys), default=None),
            "last_signal": max((s["date"] for s in buys), default=None),
            "ret_5d": _stats([s.get("ret_5d") for s in buys]),
            "producers": sorted({s["producer"] for s in buys}),
        },
    })


@app.get("/api/tickers", dependencies=[Depends(fresh)])
def tickers(q: str = ""):
    return clean({"tickers": STORE.search_tickers(q)})


@app.get("/api/analytics", dependencies=[Depends(fresh)])
def analytics_view(producer: str = None, date_from: str = None, date_to: str = None):
    if producer and producer not in STORE.producers:
        raise HTTPException(404, f"unknown producer {producer}")
    return clean(analytics(producer, date_from, date_to))


DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT)
