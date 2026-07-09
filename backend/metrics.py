"""Signal enrichment (forward performance) and analytics aggregates.

Purely signal + price based — this dashboard is decoupled from the trading
arena and only exposes what the producers generated and how it moved.
"""
from collections import defaultdict
from datetime import date as _date
from statistics import median

from .store import STORE

HORIZONS = (1, 5, 20)


def enrich(rec, spark=False):
    """Attach entry price, forward returns and a performance status."""
    out = dict(rec)
    ticker, dt = rec["ticker"], rec["date"]
    entry = rec.get("price")
    try:
        entry = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        entry = None
    if not entry:
        entry = STORE.price_on(ticker, dt)
    out["entry_px"] = entry

    last_px, last_date = STORE.last_price(ticker)
    out["last_px"], out["last_date"] = last_px, last_date
    for h in HORIZONS:
        px, _ = STORE.fwd_price(ticker, dt, h)
        out[f"ret_{h}d"] = (px / entry - 1) if (px and entry) else None
    has_fwd = last_px and entry and last_date and last_date > dt
    out["ret_since"] = (last_px / entry - 1) if has_fwd else None

    # The ticker fell out of the producers' universe: its price series (and so
    # ret_since / status_perf) is frozen at last_date, not current.
    all_dates = STORE.all_dates
    latest_run = all_dates[-1] if all_dates else None
    out["px_stale"] = bool(last_date and latest_run and last_date < latest_run)

    if rec.get("decision") != "BUY":
        out["status_perf"] = "no_action"
    elif entry is None:
        # "pending" must mean "resolves on a future close". If the ticker has
        # no price series, dropped out of the scored universe (px_stale), or
        # its series already moved past the signal date, no entry price can
        # ever appear — surface that instead of pending.
        resolvable = (last_date is not None and dt > last_date
                      and not out["px_stale"])
        out["status_perf"] = "pending" if resolvable else "no_px"
    elif not has_fwd:
        out["status_perf"] = "pending"
    elif out["ret_since"] > 0.001:
        out["status_perf"] = "up"
    elif out["ret_since"] < -0.001:
        out["status_perf"] = "down"
    else:
        out["status_perf"] = "flat"

    if spark:
        series = STORE.series(ticker)
        i = next((k for k, p in enumerate(series) if p["date"] >= dt), None)
        if i is not None:
            window = series[max(0, i - 3):]
            out["spark"] = {
                "px": [round(p["px"], 6) for p in window[-45:]],
                "signal_i": min(i, 3) if len(window) <= 45 else None,
            }
            # if truncated from the left, recompute marker index
            if out["spark"]["signal_i"] is None:
                w = window[-45:]
                out["spark"]["signal_i"] = next(
                    (k for k, p in enumerate(w) if p["date"] >= dt), None)
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

    timeline = defaultdict(lambda: {"date": None})
    for p in STORE.producers.values():
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
    for name in STORE.producers:
        prows = [r for r in rows if r["producer"] == name]
        by_producer[name] = {
            "n_signals": len(prows),
            "n_pending": sum(1 for r in prows if r["status_perf"] == "pending"),
            "n_no_px": sum(1 for r in prows if r["status_perf"] == "no_px"),
            "n_up": sum(1 for r in prows if r["status_perf"] == "up"),
            "n_down": sum(1 for r in prows if r["status_perf"] == "down"),
            "horizons": {f"{h}d": _stats([r.get(f"ret_{h}d") for r in prows])
                         for h in HORIZONS},
            "since": _stats([r.get("ret_since") for r in prows]),
        }

    # cumulative equal-weight return of taking every BUY at close, 1-day hold
    cumulative = []
    daily = defaultdict(dict)
    for name in STORE.producers:
        by_date = defaultdict(list)
        for r in rows:
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
               for r in rows if r.get("metric") is not None]

    sig_metric = {n: [r["metric"] for r in rows
                      if r["producer"] == n and r.get("metric") is not None]
                  for n in STORE.producers}
    histograms = {}
    buckets = {}
    for name, prod in STORE.producers.items():
        lo, hi = prod.spec.get("hist_range", (0.0, 1.0))
        n_bins = prod.spec.get("hist_bins", 20)
        universe = [v for v in prod.metric_values
                    if isinstance(v, (int, float)) and lo <= v <= hi]
        signals = [v for v in sig_metric.get(name, [])
                   if isinstance(v, (int, float)) and lo <= v <= hi]
        histograms[name] = _histogram(universe, signals, lo, hi, n_bins)
        buckets[name] = _buckets(
            [r for r in rows if r["producer"] == name],
            prod.spec["metric"],
        )

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    weekday = []
    for wd in range(5):
        sel = [r for r in rows
               if _date.fromisoformat(r["date"]).weekday() == wd]
        weekday.append({"day": weekdays[wd], "n": len(sel),
                        **_stats([r.get("ret_5d") for r in sel])})

    ranked = sorted((r for r in rows if r.get("ret_since") is not None),
                    key=lambda r: r["ret_since"])
    slim = lambda r: {k: r.get(k) for k in
                      ("id", "producer", "date", "ticker", "metric",
                       "entry_px", "ret_since", "status_perf")}

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
