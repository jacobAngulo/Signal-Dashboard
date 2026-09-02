"""Signal enrichment (forward performance) and analytics aggregates.

Purely signal + price based — this dashboard is decoupled from execution
systems and only exposes what the producers generated and how it moved.
"""
from collections import defaultdict
from datetime import date as _date
import math
from statistics import median

from . import trading_days
from .store import STORE

HORIZONS = (1, 5, 20)

# TB-46: per-producer holding window, in XNYS trading sessions. Copied by
# value from the LSTM repo's own dataset builder rather than imported, so this
# repo stays decoupled from that one -- see docs/TB-46-signal-windows-plan.md.
LSTM_HORIZON_SESSIONS = {"1d": 1, "1w": 5, "1m": 21, "6m": 126}


def _finite(v):
    """`v` as a float, or None if it's missing, NaN, or not numeric."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _text(v):
    """`v` as a stripped string, or None if it's missing/blank/NaN."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    text = str(v).strip()
    return text or None


_WINDOW_NONE = {
    "window_label": None, "window_sessions": None,
    "window_basis": None, "window_note": None,
}


def _window(rec):
    """Per-producer holding window, or None when the producer has none.

    Deliberately not unified into a single number: LSTM publishes a real
    session count, foundry publishes a word an LLM chose, intrinsic publishes
    nothing. Flattening those into one scale would be inventing data.
    """
    producer = rec.get("producer")
    if producer == "lstm":
        if rec.get("tier") == "lstm_attention":
            # The attention tier carries its own expected holding horizon,
            # distinct from `best_horizon` (the model's strongest head, not
            # the attention window). Fall back to best_horizon only when the
            # attention-specific field is absent.
            sessions = _finite(rec.get("attention_horizon_sessions"))
            if sessions is not None:
                sessions = int(sessions)
                return {
                    "window_label": f"{sessions} sessions",
                    "window_sessions": sessions,
                    "window_basis": "attention_horizon",
                    "window_note": "attention tier expected holding horizon",
                }
            horizon = _text(rec.get("best_horizon"))
            sessions = LSTM_HORIZON_SESSIONS.get(horizon) if horizon else None
            return {
                "window_label": horizon,
                "window_sessions": sessions,
                "window_basis": "producer_horizon" if horizon else None,
                "window_note": (
                    f"model horizon — {sessions} trading sessions"
                    if sessions is not None
                    else "model horizon" if horizon else None
                ),
            }
        horizon = _text(rec.get("horizon"))
        if horizon is None:
            return dict(_WINDOW_NONE)
        sessions = LSTM_HORIZON_SESSIONS.get(horizon)
        return {
            "window_label": horizon,
            "window_sessions": sessions,
            "window_basis": "producer_horizon",
            "window_note": (
                f"model horizon — {sessions} trading sessions"
                if sessions is not None
                # Never guess: an unrecognized horizon string is still shown
                # verbatim, but with no invented session count.
                else "model horizon — unrecognized value, published verbatim"
            ),
        }
    if producer == "foundry":
        horizon = _text(rec.get("horizon"))
        if horizon is None:
            return dict(_WINDOW_NONE)
        return {
            "window_label": horizon,
            "window_sessions": None,
            "window_basis": "llm_time_sensitivity",
            "window_note": (
                "the extraction model's own word (intraday/swing/long_term); "
                "not a session count — see TB-57"
            ),
        }
    if producer == "intrinsic":
        return {
            **_WINDOW_NONE,
            "window_note": (
                "valuation snapshot — this producer publishes no holding window"
            ),
        }
    return dict(_WINDOW_NONE)


_EXIT_NONE = {
    "exit_basis": None, "exit_state": None, "exit_date": None,
    "exit_px": None, "exit_return": None, "sessions_elapsed": None,
    "exit_note": None,
}


def _sessions_elapsed(ticker, start_date, end_date):
    """Trading sessions from `start_date` to `end_date`, exclusive of start.

    Prefers the forward calendar (works even when the price book has a gap);
    falls back to counting the price book's own points, which needs no
    dependency and is exact for any range that has already traded.
    """
    if start_date is None or end_date is None:
        return None
    elapsed = trading_days.sessions_between(start_date, end_date)
    if elapsed is not None:
        return elapsed
    series = STORE.series(ticker, start=start_date)
    dates = [p["date"] for p in series]
    if start_date in dates and end_date in dates:
        return dates.index(end_date) - dates.index(start_date)
    return None


def _native_exit(rec, entry_date, window_sessions):
    """When this signal's own producer logic would have sold.

    Not an execution feature: a read-only replay of already-stored prices
    against the producer's own published horizon or status, using the same
    corporate-action guard as every other return on this dashboard
    (`STORE.performance`) so a native exit can never report a number that
    return-computation elsewhere would have refused to trust.
    """
    producer = rec.get("producer")
    ticker = rec["ticker"]

    if producer == "foundry":
        return {**_EXIT_NONE, "exit_note": "this producer publishes no exit signal"}

    if producer == "lstm":
        out = dict(_EXIT_NONE)
        out["exit_basis"] = "sessions"
        if window_sessions is None:
            out["exit_note"] = "unrecognized horizon — cannot compute a native exit"
            return out
        if entry_date is None:
            out["exit_note"] = "no confirmed entry session yet"
            return out
        perf = STORE.performance(ticker, entry_date, sessions=window_sessions)
        reason = perf.get("blocked_reason")
        if reason == "pending_exit_session":
            out["exit_state"] = "open"
            out["exit_date"] = trading_days.session_offset(entry_date, window_sessions)
            last = perf.get("last") or {}
            out["sessions_elapsed"] = _sessions_elapsed(ticker, entry_date, last.get("date"))
            out["exit_note"] = "model horizon not yet reached"
        elif reason == "corporate_action_unresolved":
            # The producer's time-based exit still happened on a known session;
            # only the cross-boundary return is unsafe. Preserve the native exit
            # state/date and withhold the return, matching `exit_state`'s
            # contract that None means the producer has no native exit.
            exit_point = perf.get("exit") or {}
            out["exit_state"] = "closed"
            out["exit_date"] = exit_point.get("date")
            out["exit_px"] = exit_point.get("px")
            out["sessions_elapsed"] = window_sessions
            out["exit_note"] = (
                "model horizon reached, but the return crosses an unresolved "
                "corporate action"
            )
        elif reason is not None:
            out["exit_note"] = reason
        elif perf.get("return") is not None:
            exit_point = perf.get("exit") or {}
            out["exit_state"] = "closed"
            out["exit_date"] = exit_point.get("date")
            out["exit_px"] = exit_point.get("px")
            out["exit_return"] = perf.get("return")
            out["sessions_elapsed"] = window_sessions
            out["exit_note"] = "model horizon reached"
        return out

    if producer == "intrinsic":
        out = dict(_EXIT_NONE)
        out["exit_basis"] = "producer_status"
        if entry_date is None:
            out["exit_note"] = "no confirmed entry session yet"
            return out
        # getattr, not a direct call: some test doubles patch `STORE` with a
        # minimal stand-in that predates this method. Real Store always has
        # it (backend/store.py) -- this only guards against an incomplete
        # fixture, never real behavior.
        status_exit = getattr(STORE, "producer_status_exit", None)
        exit_date = (
            status_exit("intrinsic", ticker, entry_date, "exit_candidate")
            if status_exit is not None else None
        )
        if exit_date is None:
            out["exit_state"] = "open"
            out["exit_note"] = "price has not reached intrinsic value yet"
            return out
        out["exit_state"] = "closed"
        out["exit_date"] = exit_date
        sessions = _sessions_elapsed(ticker, entry_date, exit_date)
        out["sessions_elapsed"] = sessions
        if sessions is not None:
            perf = STORE.performance(ticker, entry_date, sessions=sessions)
            if perf.get("return") is not None:
                exit_point = perf.get("exit") or {}
                out["exit_px"] = exit_point.get("px")
                out["exit_return"] = perf.get("return")
            elif perf.get("blocked_reason") == "corporate_action_unresolved":
                out["exit_note"] = (
                    "status flipped, but the return crosses an unresolved "
                    "corporate action"
                )
        return out

    return dict(_EXIT_NONE)


def enrich(rec, spark=False, directional=None):
    """Attach entry price, forward returns and a performance status.

    `directional` decides whether the row gets an up/down/flat reading or the
    inert `no_action`. It defaults to "this was a BUY", because a SELL or WATCH
    row has no long position whose direction would mean anything. LSTM score
    candidates pass it explicitly: they carry BUY semantics and were simply not
    the day's single winner, so reading their direction is the whole point of
    the candidate view.
    """
    out = dict(rec)
    ticker, dt = rec["ticker"], rec["date"]
    signal_price = rec.get("signal_price")
    if signal_price is None:
        signal_price = rec.get("price", rec.get("close"))
    try:
        signal_price = float(signal_price) if signal_price is not None else None
    except (TypeError, ValueError):
        signal_price = None
    out["signal_price"] = signal_price

    # Entry anchors at the signal, not the actionable session: the close of
    # the last session on/before the signal existed. Daily producers score off
    # their date's close; foundry events become actionable the session *after*
    # publication (the `date` bucketing), so their anchor is the prior close
    # and ret_since includes the overnight gap the event traded on. The
    # actionable-session view is kept alongside (ret_1d/5d/20d and
    # ret_since_actionable) — it stays pending until that session trades.
    snap = "before" if rec.get("producer") == "foundry" else "on_or_before"
    since = STORE.performance(ticker, dt, through_last=True, entry_snap=snap)
    actionable = STORE.performance(ticker, dt, through_last=True)
    if since.get("entry") is None and actionable.get("entry") is not None:
        # No session precedes the signal (coverage starts on the actionable
        # day, e.g. a new listing) — the actionable close is the entry.
        since = actionable
    entry_point = since.get("entry") or {}
    last_point = since.get("last") or actionable.get("last") or {}
    entry = entry_point.get("px")
    entry_date = entry_point.get("date")
    last_px, last_date = last_point.get("px"), last_point.get("date")
    out["entry_px"] = entry
    out["entry_date"] = entry_date
    out["last_px"], out["last_date"] = last_px, last_date
    out["actionable_entry_px"] = (actionable.get("entry") or {}).get("px")
    out["ret_since_actionable"] = (
        actionable.get("return") if last_date and last_date > dt else None
    )
    horizon_results = {}
    for h in HORIZONS:
        result = STORE.performance(ticker, dt, sessions=h)
        horizon_results[h] = result
        out[f"ret_{h}d"] = result.get("return")
        out[f"ret_{h}d_blocked_reason"] = result.get("blocked_reason")
    out["ret_since"] = (
        since.get("return")
        if entry_date and last_date and last_date > entry_date else None
    )
    out["ret_since_blocked_reason"] = since.get("blocked_reason")
    out["blocked_return_reason"] = (
        since.get("blocked_reason")
        if since.get("blocked_reason") == "corporate_action_unresolved"
        else next(
            (out[f"ret_{h}d_blocked_reason"] for h in HORIZONS
             if out[f"ret_{h}d_blocked_reason"] == "corporate_action_unresolved"),
            since.get("blocked_reason"),
        )
    )
    action_results = [since, actionable, *horizon_results.values()]
    out["action_warning_ids"] = sorted({
        str(action_id)
        for result in action_results
        for action_id in (
            result.get("action_warning_ids")
            or result.get("blocked_action_ids")
            or []
        )
        if not str(action_id).startswith("coverage:")
    })
    out["has_action_warning"] = bool(out["action_warning_ids"])
    out["price_basis"] = since.get("price_basis", entry_point.get("price_basis"))
    out["action_status"] = since.get(
        "confirmation_status", entry_point.get("confirmation_status")
    )
    out["blocked_action_ids"] = since.get("blocked_action_ids", [])
    out["action_revision"] = since.get("action_revision", entry_point.get("action_revision"))
    out["continuity_segments"] = since.get(
        "continuity_segments",
        [entry_point.get("continuity_segment")] if entry_point else [],
    )
    has_fwd = out["ret_since"] is not None
    status_return = out["ret_since"]
    out["status_basis"] = "since" if status_return is not None else None
    if status_return is None:
        # If "since" crosses an uncertain boundary, retain the longest
        # trustworthy forward window as the signal's useful direction. The
        # separate action flag explains why longer returns are absent.
        for h in reversed(HORIZONS):
            if out[f"ret_{h}d"] is not None:
                status_return = out[f"ret_{h}d"]
                out["status_basis"] = f"{h}d"
                break

    # The ticker fell out of the gateway's coverage: its price series (and so
    # ret_since / status_perf) is frozen at last_date, not current. Compared
    # against the book's own latest session — the producer calendar includes
    # the next actionable day, which would flag every latest-bucket signal.
    book_last = STORE.price_max_date
    out["px_stale"] = bool(last_date and book_last and last_date < book_last)

    if not (rec.get("decision") == "BUY" if directional is None else directional):
        out["status_perf"] = "no_action"
    elif entry is None:
        # "pending" must mean "resolves on a future close". If the ticker has
        # no price series, dropped out of the scored universe (px_stale), or
        # its series already moved past the signal date, no entry price can
        # ever appear — surface that instead of pending.
        resolvable = (last_date is not None and dt > last_date
                      and not out["px_stale"])
        out["status_perf"] = "pending" if resolvable else "no_px"
    elif status_return is None and out["blocked_return_reason"] == "corporate_action_unresolved":
        out["status_perf"] = "return_limited"
    elif not has_fwd and status_return is None:
        out["status_perf"] = "pending"
    elif status_return > 0.001:
        out["status_perf"] = "up"
    elif status_return < -0.001:
        out["status_perf"] = "down"
    else:
        out["status_perf"] = "flat"

    out.update(_window(out))
    out.update(_native_exit(out, entry_date, out["window_sessions"]))

    if spark:
        series = STORE.series(ticker)
        if series:
            # The trend is ticker data, not signal data: always render the
            # trailing window; the marker sits on the entry anchor and simply
            # drops off when it precedes the window (or hasn't traded yet).
            mark = entry_date or dt
            i = next((k for k, p in enumerate(series) if p["date"] >= mark), None)
            window = series if i is None else series[max(0, i - 3):]
            w = window[-45:]
            out["spark"] = {
                "px": [round(p["px"], 6) for p in w],
                "signal_i": next(
                    (k for k, p in enumerate(w) if p["date"] >= mark), None),
            }
    return out


def enriched_decisions(producer=None, date_from=None, date_to=None,
                       ticker=None, buys_only=False, spark=False):
    rows = []
    for rec in STORE.all_decisions:
        if producer and rec["producer"] != producer:
            continue
        if date_from and rec["date"] < date_from:
            continue
        if date_to and rec["date"] > date_to:
            continue
        if ticker and rec["ticker"] != ticker.upper():
            continue
        if buys_only and rec.get("decision") != "BUY":
            continue
        rows.append(enrich(rec, spark=spark))
    return rows


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n": 0, "win_rate": None, "avg": None, "median": None}
    return {
        "n": len(vals),
        "win_rate": sum(1 for v in vals if v > 0) / len(vals),
        "avg": sum(vals) / len(vals),
        "median": median(vals),
    }


def _buckets(rows, field, n_buckets=4):
    vals = sorted(r[field] for r in rows if r.get(field) is not None)
    if len(vals) < n_buckets * 2:
        return []
    edges = [vals[int(len(vals) * i / n_buckets)] for i in range(1, n_buckets)]
    buckets = []
    for i in range(n_buckets):
        lo = edges[i - 1] if i else None
        hi = edges[i] if i < n_buckets - 1 else None
        members = [r for r in rows if r.get(field) is not None
                   and (lo is None or r[field] >= lo)
                   and (hi is None or r[field] < hi)]
        label = f"{lo:.3f}" if lo is not None else "min"
        label += " – " + (f"{hi:.3f}" if hi is not None else "max")
        buckets.append({
            "label": label,
            "n": len(members),
            **{f"ret_{h}d": _stats([m.get(f"ret_{h}d") for m in members])
               for h in HORIZONS},
        })
    return buckets


def _histogram(universe, signals, lo, hi, n_bins):
    """Share-normalized distribution: signal metric vs whole score universe."""
    step = (hi - lo) / n_bins
    bins = []
    u_tot = len(universe) or 1
    s_tot = len(signals) or 1
    for i in range(n_bins):
        b_lo, b_hi = lo + i * step, lo + (i + 1) * step
        last = i == n_bins - 1
        u = sum(1 for v in universe if b_lo <= v < b_hi or (last and v >= b_hi))
        s = sum(1 for v in signals if b_lo <= v < b_hi or (last and v >= b_hi))
        bins.append({"lo": round(b_lo, 4), "label": f"{b_lo:.2f}",
                     "universe": u / u_tot, "signals": s / s_tot,
                     "n_universe": u, "n_signals": s})
    return bins


def analytics(producer=None, date_from=None, date_to=None):
    rows = enriched_decisions(producer, date_from, date_to, buys_only=True)
    producer_names = [producer] if producer else list(STORE.producers)
    # Each return field is already independently fail-closed when its own
    # window crosses an uncertain action. Safe horizons on the same signal
    # remain eligible instead of discarding the entire row.
    performance_rows = rows

    timeline = defaultdict(lambda: {"date": None})
    for name in producer_names:
        p = STORE.producers[name]
        for run in p.run_rows():
            if date_from and run["date"] < date_from:
                continue
            if date_to and run["date"] > date_to:
                continue
            t = timeline[run["date"]]
            t["date"] = run["date"]
            t[f"{run['producer']}_buys"] = run["n_buy"]
            t[f"{run['producer']}_status"] = run["status"]

    by_producer = {}
    for name in producer_names:
        prows = [r for r in rows if r["producer"] == name]
        eligible = [r for r in performance_rows if r["producer"] == name]
        by_producer[name] = {
            "n_signals": len(prows),
            "n_pending": sum(1 for r in prows if r["status_perf"] == "pending"),
            "n_no_px": sum(1 for r in prows if r["status_perf"] == "no_px"),
            "n_corporate_action_unresolved": sum(
                1 for r in prows if r.get("has_action_warning")
            ),
            "n_up": sum(1 for r in prows if r["status_perf"] == "up"),
            "n_down": sum(1 for r in prows if r["status_perf"] == "down"),
            "horizons": {f"{h}d": _stats([r.get(f"ret_{h}d") for r in eligible])
                         for h in HORIZONS},
            "since": _stats([r.get("ret_since") for r in eligible]),
        }

    # cumulative equal-weight return of taking every BUY at close, 1-day hold
    cumulative = []
    daily = defaultdict(dict)
    for name in producer_names:
        by_date = defaultdict(list)
        for r in performance_rows:
            if r["producer"] == name and r.get("ret_1d") is not None:
                by_date[r["date"]].append(r["ret_1d"])
        level = 1.0
        for dt in sorted(by_date):
            level *= 1 + sum(by_date[dt]) / len(by_date[dt])
            daily[dt][name] = level
    running = {}
    for dt in sorted(daily):
        running.update(daily[dt])
        cumulative.append({"date": dt, **{k: round(v, 6) for k, v in running.items()}})

    scatter = [{"ticker": r["ticker"], "date": r["date"], "producer": r["producer"],
                "metric": r.get("metric"), "ret_5d": r.get("ret_5d"),
                "ret_since": r.get("ret_since")}
               for r in performance_rows
               if r.get("metric") is not None and r.get("ret_5d") is not None]

    sig_metric = {n: [r["metric"] for r in rows
                      if r["producer"] == n and r.get("metric") is not None]
                  for n in producer_names}
    histograms = {}
    buckets = {}
    for name in producer_names:
        prod = STORE.producers[name]
        lo, hi = prod.spec.get("hist_range", (0.0, 1.0))
        n_bins = prod.spec.get("hist_bins", 20)
        metric_col = prod.spec.get("history_metric", prod.spec.get("metric", "metric"))
        universe = []
        score_frames = getattr(prod, "scores", None)
        if score_frames is None:
            score_frames = {"": {metric_col: getattr(prod, "metric_values", [])}}
        for dt, frame in score_frames.items():
            if dt and ((date_from and dt < date_from) or (date_to and dt > date_to)):
                continue
            columns = getattr(frame, "columns", frame)
            if metric_col not in columns:
                continue
            for raw in frame[metric_col]:
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if lo <= value <= hi:
                    universe.append(value)
        signals = [v for v in sig_metric.get(name, [])
                   if isinstance(v, (int, float)) and lo <= v <= hi]
        histograms[name] = _histogram(universe, signals, lo, hi, n_bins)
        buckets[name] = _buckets(
            [r for r in performance_rows if r["producer"] == name],
            prod.spec["metric"],
        )

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    weekday = []
    for wd in range(5):
        sel = [r for r in performance_rows
               if _date.fromisoformat(r["date"]).weekday() == wd
               and r.get("ret_5d") is not None]
        weekday.append({"day": weekdays[wd], "n": len(sel),
                        **_stats([r.get("ret_5d") for r in sel])})

    ranked = sorted((r for r in performance_rows if r.get("ret_since") is not None),
                    key=lambda r: r["ret_since"])
    slim = lambda r: {k: r.get(k) for k in
                      ("id", "producer", "date", "ticker", "metric",
                       "entry_px", "ret_since", "status_perf",
                       "has_action_warning", "action_warning_ids",
                       "status_basis")}

    return {
        "timeline": sorted(timeline.values(), key=lambda t: t["date"] or ""),
        "by_producer": by_producer,
        "buckets": buckets,
        "cumulative": cumulative,
        "scatter": scatter,
        "histograms": histograms,
        "weekday": weekday,
        "best": [slim(r) for r in ranked[::-1][:5]],
        "worst": [slim(r) for r in ranked[:5]],
    }
