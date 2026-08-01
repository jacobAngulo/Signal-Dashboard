# Signal Dashboard

Standalone, read-only analytics UI over the **LSTM_AI_Stock_Predictor**,
**Intrinsic-Value-Monitor**, and **Signal-Foundry** signal producers. Decoupled
from execution systems — it only exposes what the producers generated and how
it moved.

Answers:

1. **What was generated, when, with what?** Every producer run (status,
   score row counts, staleness, generated-at), with drill-down from a
   calendar heatmap into per-day pages and the full ~1.3k-row score files.
2. **How are past signals doing?** Every BUY gets forward returns
   (1d / 5d / 20d / since-signal) and an up/down/pending status, computed
   from corporate-action-aware continuous gateway prices, anchored to each
   signal's causal entry session. Tickers outside price coverage get
   an explicit `no_px` status instead of an eternal "pending".
3. **Is the signal any good?** Analytics: win rates by horizon, signal
   strength vs outcome scatter, signal-vs-universe metric distributions,
   quartile buckets, cumulative take-every-BUY curves, weekday effects.

## Foundry events are trading-day aligned and gated

Foundry emits events around the clock; the daily producers emit one batch per
trading day. To live on the same calendar, each foundry event is bucketed by
the **trading day it is actionable for** using causal `extracted_at`, not a
historical publication date. Extraction timestamps convert to ET; anything
at/after 16:00 ET (and weekends/holidays) rolls to the next session. The raw
publish timestamp stays on the row (`published_at`, `event_date`) as source
context, while `as_of_timestamp` records actual extraction availability. The
overview card also surfaces the fetch/extract loop health
(queue depth, per-source freshness) straight from the foundry DB, since a
silent source otherwise looks like a quiet news day.

**One signal per ticker per trading day.** All of a ticker-day's events roll
up into a single decision row (contributing events are listed in the detail
drawer). Extracted sentiment alone never triggers a BUY/SELL: direction
weight is `signal_score × |sentiment|`, and the gate (`foundry_gate` in
config.json) requires either one event past `score_floor` (in practice a
primary-source EDGAR filing the LLM scored with conviction) or ≥2 aligned
events whose net weight passes `net_floor`, with a `dominance` share that
turns mixed-direction chatter days into WATCH. Every row carries a
`gate_reason` explaining the outcome.

## Attention and coverage states

The production BUY/SELL contracts remain unchanged. Additive WATCH rows expose
the tested research candidates: LSTM `p > 0.18` with a 1.5x prior-volume surge,
Intrinsic's shadow-only `0.075-0.65` ratio extension, and Foundry's fixed top-five
event-type-prior queue. Score browsers retain the underlying attention/shadow
columns. Run rows also merge each producer's coverage manifest, including ready
counts, ready fractions, valuation readiness, and fail-closed guard status.

## Navigation model

Hash-routed and deep-linkable: `#/` overview · `#/explore` server-filtered,
paginated signal explorer · `#/lstm-windows` all published above-threshold
LSTM candidates grouped by each ticker's strongest horizon/day, with the final
daily pick highlighted · `#/analytics` · `#/runs` ·
`#/scores/<producer>/<date>` curated raw score browser · `#/ticker/<T>`
per-ticker page (default 5-day/5-minute Alpaca IEX candlesticks with independent
lookback, 1m/5m/15m/1h/1D bar interval, Candles/OHLC/Line/Area style controls,
volume, timestamped signal markers, non-blocking descriptive insights, metric
history, and all signals) ·
`#/day/<date>` per-day page. Every ticker and date anywhere in the UI is a
link; the header has jump-to-ticker search.

Price snapshots refresh asynchronously every five minutes by default
(`price_refresh_seconds` or `PRICE_REFRESH_SECONDS`). Unresolved corporate
actions remain visible as compact `CA` flags: chart/model/signal insights still
render, same-basis post-action returns remain usable, and only return windows
that cross uncertain action evidence are excluded. Analytics eligibility is
evaluated separately for each return horizon rather than dropping the signal.
Intraday chart requests use a separate 45-second gateway cache and never alter
the daily SIP performance book.

## Architecture

- `backend/` — FastAPI (port 8010). Reads producer outputs strictly read-only:
  LSTM/Intrinsic `signals/` dirs plus Signal-Foundry's DuckDB file. It caches in
  memory and auto-reloads when source files change (mtime fingerprints). Serves
  the built frontend. `GET /api/signals` is a filterable, optionally paginated
  JSON feed; list rows use a compact contract and `GET /api/signal?id=...`
  exposes full detail on demand.
- `frontend/` — React 18 + Vite + recharts, tiny hash router (no deps).
- `deploy/` — systemd unit + nginx location block
  (served at `/signal-dashboard/`).

## Run

```bash
cp config.example.json config.json   # adjust paths if needed
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

Dev: `npm run dev` in `frontend/` (proxies `/api` to :8010).

Deploy: `cp deploy/signal-dashboard.service /etc/systemd/system/ && systemctl enable --now signal-dashboard`,
then merge `deploy/nginx-location.conf` into the nginx server block.
