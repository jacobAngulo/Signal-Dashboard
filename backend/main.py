"""Signal-Dashboard API: read-only analytics over LSTM + Intrinsic signals."""
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .config import HOST, PORT
from .metrics import analytics, enrich, enriched_decisions, _stats
from .store import STORE, clean

app = FastAPI(title="Signal Dashboard", docs_url="/api/docs", openapi_url="/api/openapi.json")


def fresh():
    STORE.refresh()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/overview", dependencies=[Depends(fresh)])
def overview():
    out = {"producers": {}, "latest_date": None, "calendar": [], "recent": {}}
    for name, prod in STORE.producers.items():
        runs = prod.run_rows()
        latest = runs[-1] if runs else None
        all_buys = enriched_decisions(producer=name, buys_only=True)
        out["producers"][name] = {
            "latest_run": latest,
            "totals": {
                "days": len(runs),
                "signals": len(all_buys),
                "win_5d": _stats([r.get("ret_5d") for r in all_buys])["win_rate"],
                "avg_5d": _stats([r.get("ret_5d") for r in all_buys])["avg"],
            },
        }
        out["calendar"].extend(runs)
        if latest and (out["latest_date"] is None or latest["date"] > out["latest_date"]):
            out["latest_date"] = latest["date"]

    latest_signals = enriched_decisions(buys_only=True, spark=True)
    latest_signals.sort(key=lambda r: (r["date"], r["producer"]), reverse=True)
    out["latest_signals"] = latest_signals[:12]

    ranked = [r for r in latest_signals if r.get("ret_since") is not None]
    ranked.sort(key=lambda r: r["ret_since"])
    slim = lambda r: {k: r.get(k) for k in
                      ("producer", "date", "ticker", "ret_since", "status_perf")}
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
                top = df.sort_values(metric, ascending=False, na_position="last") \
                        .head(12).to_dict("records")
        out["producers"][name] = {
            "run": run,
            "status_raw": prod.status.get(date),
            "decisions": enriched_decisions(producer=name, date_from=date,
                                            date_to=date, spark=True),
            "n_scores": len(df) if df is not None else 0,
            "scores_available": df is not None,
            "top_scores": top,
            "metric_col": prod.spec["history_metric"],
        }
    return clean(out)


@app.get("/api/scores/{producer}/{date}", dependencies=[Depends(fresh)])
def scores(producer: str, date: str, sort: str = None, dir: str = "desc",
           limit: int = 100, offset: int = 0, q: str = None):
    prod = STORE.producers.get(producer)
    if prod is None:
        raise HTTPException(404, f"unknown producer {producer}")
    df = prod.scores.get(date)
    if df is None:
        raise HTTPException(404, f"no scores for {producer} on {date}")
    if q and "ticker" in df.columns:
        df = df[df["ticker"].astype(str).str.upper().str.contains(q.upper(), na=False)]
    sort = sort or prod.spec["history_metric"]
    if sort in df.columns:
        df = df.sort_values(sort, ascending=(dir == "asc"), na_position="last")
    total = len(df)
    page = df.iloc[offset:offset + min(limit, 500)]
    return clean({
        "producer": producer, "date": date, "total": total,
        "columns": list(df.columns),
        "rows": page.to_dict("records"),
        "dates": prod.dates,
    })


@app.get("/api/signals", dependencies=[Depends(fresh)])
def signals(producer: str = None, ticker: str = None,
            date_from: str = None, date_to: str = None,
            buys_only: bool = True, spark: bool = True):
    rows = enriched_decisions(producer, date_from, date_to, ticker,
                              buys_only, spark=spark)
    rows.sort(key=lambda r: (r["date"], r["producer"], r["ticker"]), reverse=True)
    return clean({"signals": rows, "total": len(rows)})


@app.get("/api/ticker/{ticker}", dependencies=[Depends(fresh)])
def ticker_view(ticker: str):
    t = ticker.upper()
    sigs = enriched_decisions(ticker=t, buys_only=False)
    if not sigs and t not in STORE.prices:
        raise HTTPException(404, f"no data for {t}")
    buys = [s for s in sigs if s.get("decision") == "BUY"]
    return clean({
        "ticker": t,
        "signals": sorted(sigs, key=lambda r: r["date"], reverse=True),
        "series": STORE.series(t),
        "history": {name: prod.history.get(t, [])
                    for name, prod in STORE.producers.items()},
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
    return clean(analytics(producer, date_from, date_to))


DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT)
