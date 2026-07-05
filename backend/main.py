"""Signal-Dashboard API: read-only analytics over LSTM + Intrinsic signals."""
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .arena import ARENA
from .config import HOST, PORT
from .metrics import analytics, enriched_decisions, execution_summary
from .store import STORE, clean

app = FastAPI(title="Signal Dashboard", docs_url="/api/docs", openapi_url="/api/openapi.json")


def fresh():
    STORE.refresh()
    ARENA.refresh()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/summary", dependencies=[Depends(fresh)])
def summary():
    out = {"producers": {}, "latest_date": None}
    all_dec = STORE.all_decisions
    for name, prod in STORE.producers.items():
        runs = prod.run_rows()
        latest = runs[-1] if runs else None
        decs = []
        if latest:
            decs = enriched_decisions(producer=name, date_from=latest["date"],
                                      date_to=latest["date"])
        traded = sum(1 for r in enriched_decisions(producer=name, buys_only=True)
                     if r["exec"]["traded"])
        out["producers"][name] = {
            "latest_run": latest,
            "latest_decisions": decs,
            "recent_runs": runs[-10:][::-1],
            "totals": {
                "days": len(runs),
                "signals": sum(1 for r in all_dec
                               if r["producer"] == name and r["decision"] == "BUY"),
                "traded": traded,
            },
        }
        if latest and (out["latest_date"] is None or latest["date"] > out["latest_date"]):
            out["latest_date"] = latest["date"]
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
    out = {"date": date, "producers": {}}
    for name, prod in STORE.producers.items():
        run = next((r for r in prod.run_rows() if r["date"] == date), None)
        scores = prod.scores.get(date)
        out["producers"][name] = {
            "run": run,
            "status_raw": prod.status.get(date),
            "decisions": enriched_decisions(producer=name, date_from=date, date_to=date),
            "scores_available": scores is not None,
            "n_scores": len(scores) if scores is not None else 0,
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
    default_sort = {"lstm": "best_adj_prob", "intrinsic": "discount_to_intrinsic"}
    sort = sort or default_sort.get(producer)
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
            date_from: str = None, date_to: str = None, buys_only: bool = True):
    rows = enriched_decisions(producer, date_from, date_to, ticker, buys_only)
    rows.sort(key=lambda r: (r["date"], r["producer"], r["ticker"]), reverse=True)
    return clean({"signals": rows, "total": len(rows)})


@app.get("/api/ticker/{ticker}", dependencies=[Depends(fresh)])
def ticker_view(ticker: str):
    t = ticker.upper()
    sigs = enriched_decisions(ticker=t, buys_only=False)
    if not sigs and t not in STORE.prices:
        raise HTTPException(404, f"no data for {t}")
    return clean({
        "ticker": t,
        "signals": sorted(sigs, key=lambda r: r["date"], reverse=True),
        "series": STORE.series(t),
        "orders": ARENA.orders_by_symbol.get(t, []),
    })


@app.get("/api/analytics", dependencies=[Depends(fresh)])
def analytics_view(producer: str = None, date_from: str = None, date_to: str = None):
    return clean(analytics(producer, date_from, date_to))


@app.get("/api/execution", dependencies=[Depends(fresh)])
def execution_view():
    return clean(execution_summary())


DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT)
