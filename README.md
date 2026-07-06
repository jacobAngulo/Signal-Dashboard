# Signal Dashboard

Standalone, read-only analytics UI over the **LSTM_AI_Stock_Predictor** and
**Intrinsic-Value-Monitor** signal producers. Decoupled from the trading
arena — it only exposes what the producers generated and how it moved.

Answers:

1. **What was generated, when, with what?** Every producer run (status,
   score row counts, staleness, generated-at), with drill-down from a
   calendar heatmap into per-day pages and the full ~1.3k-row score files.
2. **How are past signals doing?** Every BUY gets forward returns
   (1d / 5d / 20d / since-signal) and an up/down/pending status, computed
   from the producers' own daily score prices — the price series is aligned
   with signal dates by construction.
3. **Is the signal any good?** Analytics: win rates by horizon, signal
   strength vs outcome scatter, signal-vs-universe metric distributions,
   quartile buckets, cumulative take-every-BUY curves, weekday effects.

## Navigation model

Hash-routed and deep-linkable: `#/` overview · `#/explore` filterable signal
explorer · `#/analytics` · `#/runs` · `#/scores/<producer>/<date>` raw score
browser · `#/ticker/<T>` per-ticker page (price with signal markers, metric
history, all signals) · `#/day/<date>` per-day page. Every ticker and date
anywhere in the UI is a link; the header has jump-to-ticker search.

## Architecture

- `backend/` — FastAPI (port 8010). Reads the two `signals/` dirs strictly
  read-only, caches in memory, auto-reloads when source files change
  (mtime fingerprints). Serves the built frontend. `GET /api/signals` is a
  clean JSON feed of enriched signals if anything else wants to consume it.
- `frontend/` — React 18 + Vite + recharts, tiny hash router (no deps).
- `deploy/` — systemd unit + nginx location block
  (served at `/signal-dashboard/`).

## Run

```bash
cp config.example.json config.json   # adjust paths if needed
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn pandas
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

Dev: `npm run dev` in `frontend/` (proxies `/api` to :8010).

Deploy: `cp deploy/signal-dashboard.service /etc/systemd/system/ && systemctl enable --now signal-dashboard`,
then merge `deploy/nginx-location.conf` into the nginx server block.
