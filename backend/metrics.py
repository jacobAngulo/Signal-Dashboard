"""Signal enrichment (forward returns + execution lifecycle) and aggregates."""
from collections import defaultdict
from statistics import median

from .arena import ARENA
from .store import STORE

HORIZONS = (1, 5, 20)


def enrich(rec):
    """Attach entry price, forward returns and arena execution to a decision."""
    out = dict(rec)
    ticker, date = rec["ticker"], rec["date"]
    entry = rec.get("price")
    try:
        entry = float(entry) if entry is not None else None
    except (TypeError, ValueError):
        entry = None
    if not entry:
        entry = STORE.price_on(ticker, date)
    out["entry_px"] = entry

    last_px, last_date = STORE.last_price(ticker)
    out["last_px"], out["last_date"] = last_px, last_date
    for h in HORIZONS:
        px, _ = STORE.fwd_price(ticker, date, h)
        out[f"ret_{h}d"] = (px / entry - 1) if (px and entry) else None
    out["ret_since"] = (last_px / entry - 1) if (last_px and entry and last_date and last_date > date) else None

    ex = ARENA.match_signal(rec["producer"], date, ticker) if rec.get("decision") == "BUY" else {"traded": False}
    out["exec"] = ex
    if rec.get("decision") != "BUY":
        out["state"] = "no_action"
    elif not ex["traded"]:
        out["state"] = "not_traded"
    else:
        out["state"] = ex["state"]
    return out


def enriched_decisions(producer=None, date_from=None, date_to=None,
                       ticker=None, buys_only=False):
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
        rows.append(enrich(rec))
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


def analytics(producer=None, date_from=None, date_to=None):
    rows = enriched_decisions(producer, date_from, date_to, buys_only=True)

    # per-day timeline (all producers kept so the chart can stack them)
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
    for r in rows:
        t = timeline[r["date"]]
        key = f"{r['producer']}_traded"
        t[key] = t.get(key, 0) + (1 if r["exec"]["traded"] else 0)

    by_producer = {}
    for name in STORE.producers:
        prows = [r for r in rows if r["producer"] == name]
        traded = [r for r in prows if r["exec"]["traded"]]
        by_producer[name] = {
            "n_signals": len(prows),
            "n_traded": len(traded),
            "horizons": {f"{h}d": _stats([r.get(f"ret_{h}d") for r in prows])
                         for h in HORIZONS},
            "since": _stats([r.get("ret_since") for r in prows]),
            "realized_pnl": sum(r["exec"].get("realized_pnl") or 0 for r in traded),
            "unrealized_pnl": sum(r["exec"].get("unrealized_pnl") or 0 for r in traded),
        }

    # cumulative equal-weight return of taking every BUY at close, per producer
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

    ranked = sorted((r for r in rows if r.get("ret_since") is not None),
                    key=lambda r: r["ret_since"])
    slim = lambda r: {k: r.get(k) for k in
                      ("id", "producer", "date", "ticker", "metric",
                       "entry_px", "ret_since", "state")}

    return {
        "timeline": sorted(timeline.values(), key=lambda t: t["date"] or ""),
        "by_producer": by_producer,
        "buckets": {
            "lstm": _buckets([r for r in rows if r["producer"] == "lstm"], "adj_prob"),
            "intrinsic": _buckets([r for r in rows if r["producer"] == "intrinsic"],
                                  "discount_to_intrinsic"),
        },
        "cumulative": cumulative,
        "best": [slim(r) for r in ranked[::-1][:5]],
        "worst": [slim(r) for r in ranked[:5]],
    }


def execution_summary():
    trips = ARENA.round_trips()
    live = ARENA.live_prices()
    by_bot = defaultdict(lambda: {"trips": 0, "wins": 0, "pnl": 0.0})
    for t in trips:
        b = by_bot[t["bot"]]
        b["trips"] += 1
        b["wins"] += 1 if t["pnl"] > 0 else 0
        b["pnl"] += t["pnl"]

    open_rows = []
    for (bot_id, symbol), lot_list in ARENA.open_lots().items():
        for lot in lot_list:
            px = live.get(symbol)
            open_rows.append({
                "bot": lot["bot"], "symbol": symbol, "producers": lot["producers"],
                "entry_date": lot["date"], "qty": lot["qty"], "entry_px": lot["px"],
                "cost": lot["qty"] * lot["px"],
                "live_px": px,
                "unrealized_pnl": lot["qty"] * (px - lot["px"]) if px else None,
                "ret": (px / lot["px"] - 1) if (px and lot["px"]) else None,
            })
    open_rows.sort(key=lambda r: r["entry_date"], reverse=True)

    recent = sorted(ARENA.orders, key=lambda o: o["timestamp"] or "", reverse=True)[:80]
    return {
        "round_trips": sorted(trips, key=lambda t: t["exit_date"], reverse=True),
        "by_bot": [{"bot": k, **v, "win_rate": v["wins"] / v["trips"] if v["trips"] else None}
                   for k, v in sorted(by_bot.items(), key=lambda kv: -kv[1]["pnl"])],
        "open_positions": open_rows,
        "recent_orders": recent,
        "totals": {
            "realized_pnl": sum(t["pnl"] for t in trips),
            "n_trips": len(trips),
            "win_rate": (sum(1 for t in trips if t["pnl"] > 0) / len(trips)) if trips else None,
            "open_cost": sum(r["cost"] for r in open_rows),
            "open_unrealized": sum(r["unrealized_pnl"] or 0 for r in open_rows),
        },
    }
