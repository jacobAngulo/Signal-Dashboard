# Signal Dashboard

Standalone, read-only analytics UI over the **LSTM_AI_Stock_Predictor**,
**Intrinsic-Value-Monitor**, and **Signal-Foundry** signal producers. Decoupled
from the trading arena — it only exposes what the producers generated and how
it moved.

Answers:

1. **What was generated, when, with what?** Every producer run (status,
   score row counts, staleness, generated-at), with drill-down from a
   calendar heatmap into per-day pages and the full ~1.3k-row score files.
2. **How are past signals doing?** Every BUY gets forward returns
   (1d / 5d / 20d / since-signal) and an up/down/pending status, computed
   from the producers' own daily score prices — the price series is aligned
   with signal dates by construction. Tickers outside the scored universe get
   an explicit `no_px` status instead of an eternal "pending".
3. **Is the signal any good?** Analytics: win rates by horizon, signal
   strength vs outcome scatter, signal-vs-universe metric distributions,
   quartile buckets, cumulative take-every-BUY curves, weekday effects.

## Foundry events are trading-day aligned

Foundry emits events around the clock; the daily producers emit one batch per
trading day. To live on the same calendar, each foundry event is bucketed by
the **trading day it is actionable for**: publish timestamps convert to ET,
anything at/after 16:00 ET (and weekends/holidays) rolls to the next session —
the same convention as Signal-Foundry's own backtest, so the score-file entry
price is the pre-event close by construction. The raw publish timestamp stays
on the row (`published_at`, `event_date`) and is what the UI shows as the
signal time. The overview card also surfaces the fetch/extract loop health
(queue depth, per-source freshness) straight from the foundry DB, since a
silent source otherwise looks like a quiet news day.

## Navigation model

Hash-routed and deep-linkable: `#/` overview · `#/explore` filterable signal
explorer · `#/analytics` · `#/runs` · `#/scores/<producer>/<date>` raw score
browser · `#/ticker/<T>` per-ticker page (price with signal markers, metric
history, all signals) · `#/day/<date>` per-day page. Every ticker and date
anywhere in the UI is a link; the header has jump-to-ticker search.

## Architecture

- `backend/` — FastAPI (port 8010). Reads producer outputs strictly read-only:
  LSTM/Intrinsic `signals/` dirs plus Signal-Foundry's DuckDB file. It caches in
  memory and auto-reloads when source files change (mtime fingerprints). Serves
  the built frontend. `GET /api/signals` is a clean JSON feed of enriched
  signals if anything else wants to consume it.
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
