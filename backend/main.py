"""Signal-Dashboard API: read-only analytics over LSTM, Intrinsic, and Foundry signals."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

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
)


def _signal_summary(row):
    """Stable, compact list contract; full raw fields live in /api/signal."""
    return {key: row.get(key) for key in SIGNAL_SUMMARY_FIELDS if key in row}


def _slice_summary(rows):
    ret_1d = _stats([row.get("ret_1d") for row in rows])
    ret_5d = _stats([row.get("ret_5d") for row in rows])
    ret_since = _stats([row.get("ret_since") for row in rows])
    statuses = {}
    for row in rows:
        status = row.get("status_perf") or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "n": len(rows),
        "wr_1d": ret_1d["win_rate"],
        "wr_5d": ret_5d["win_rate"],
        "avg_5d": ret_5d["avg"],
        "avg_since": ret_since["avg"],
        "statuses": statuses,
    }


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


@app.get("/api/lstm/windows", dependencies=[Depends(fresh)])
def lstm_windows(date_from: str = None, date_to: str = None):
    """Published LSTM candidates grouped by each ticker's strongest horizon.

    Daily decision files contain one global winner. Score files contain the
    wider above-threshold candidate universe, but deliberately persist only
    each ticker's best of the four model heads. This endpoint exposes all of
    that published evidence without inventing the discarded head values.
    """
    prod = STORE.producers["lstm"]
    windows = ["1d", "1w", "1m", "6m"]
    selected = {
        (row.get("date"), row.get("ticker"), row.get("horizon"))
        for row in prod.decisions
        if row.get("decision") == "BUY"
    }
    days = []
    counts = {window: 0 for window in windows}
    scored_counts = {window: 0 for window in windows}

    for date in sorted(prod.scores, reverse=True):
        if (date_from and date < date_from) or (date_to and date > date_to):
            continue
        frame = prod.scores[date]
        grouped = {window: [] for window in windows}
        best_horizon_counts = {window: 0 for window in windows}
        if "ticker" in frame.columns and "best_horizon" in frame.columns:
            for index, row in enumerate(records(frame)):
                ticker_value = row.get("ticker")
                horizon_value = row.get("best_horizon")
                ticker = str(ticker_value).strip().upper() if ticker_value is not None else ""
                horizon = str(horizon_value).strip() if horizon_value is not None else ""
                if not ticker or horizon not in grouped:
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
                    "as_of_close_date": row.get("as_of_close_date"),
                    "as_of_timestamp": row.get("as_of_timestamp"),
                    "as_of_source": row.get("as_of_source"),
                    "selected": (date, ticker, horizon) in selected,
                    "detail_inline": True,
                }
                grouped[horizon].append(candidate)
                counts[horizon] += 1
        for rows in grouped.values():
            rows.sort(key=lambda row: (-float(row.get("adj_prob") or 0), row["ticker"]))
        days.append({
            "date": date,
            "signals": grouped,
            "candidate_counts": {window: len(grouped[window]) for window in windows},
            "best_horizon_counts": best_horizon_counts,
            "total": sum(len(rows) for rows in grouped.values()),
            "scored": sum(best_horizon_counts.values()),
        })

    return clean({
        "windows": windows,
        "counts": counts,
        "scored_counts": scored_counts,
        "days": days,
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
            offset: int = Query(0, ge=0)):
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
        page = [enrich(row, spark=True) for row in page]
    return clean({
        "signals": [_signal_summary(row) for row in page],
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": _slice_summary(rows),
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
def ticker_view(ticker: str):
    t = ticker.upper()
    sigs = enriched_decisions(ticker=t, buys_only=False)
    history = {name: prod.history.get(t, [])
               for name, prod in STORE.producers.items()}
    if not sigs and t not in STORE.prices and not any(history.values()):
        raise HTTPException(404, f"no data for {t}")
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
