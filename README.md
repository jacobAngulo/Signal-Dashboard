# Signal Dashboard

Read-only analytics UI over the **LSTM_AI_Stock_Predictor** and
**Intrinsic-Value-Monitor** signal producers, cross-referenced with
**Trading-Bot-Arena** execution.

Answers three questions:

1. **What was generated, when, with what?** Every producer run (premarket
   verifier status, score row counts, staleness, decision files) — Today and
   Runs tabs, with drill-down into the full ~1.3k-row daily score files.
2. **How did past signals do?** Every BUY decision gets forward returns
   (1d / 5d / 20d / since-signal) computed from the producers' own daily score
   prices, so the price series is aligned with signal dates by construction.
3. **What happened in the arena?** Signals are matched to bot orders from
   `arena.sqlite3` (traded / open / partial / closed, realized P&L per lot,
   FIFO round trips). Live prices for open lots come from the arena API,
   which is Alpaca-authoritative — locally derived P&L is never treated as
   truth.

## Architecture

- `backend/` — FastAPI (port 8010). Reads the two `signals/` dirs and
  `arena.sqlite3` strictly read-only, caches in memory, auto-reloads when the
  source files change (mtime fingerprints). Serves the built frontend.
- `frontend/` — React 18 + Vite + recharts. Tabs: Today, Signals (explorer
  with lifecycle status per signal), Runs, Scores (paginated browser over raw
  score files), Analytics (win rates, prob/discount buckets, cumulative
  curves, best/worst), Execution (fleet ground truth: round trips, open lots,
  orders).
- `deploy/` — systemd unit + nginx location block (served at
  `/signal-dashboard/` behind the existing arena nginx server).

Note on semantics: the producers' `live_decision`/`intrinsic_decision` files
are flagship picks; arena bot families trade broader slices of the score
files (top-N, per-horizon thresholds). So a decision can be "not traded"
while the fleet was very active that day — the Execution tab shows the
fleet's actual behavior.

## Run

```bash
cp config.example.json config.json   # adjust paths if needed
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn pandas
cd frontend && npm install && npm run build && cd ..
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

Dev: `npm run dev` in `frontend/` (proxies `/api` to :8010).

Deploy: `cp deploy/signal-dashboard.service /etc/systemd/system/ && systemctl enable --now signal-dashboard`,
then merge `deploy/nginx-location.conf` into the arena nginx server block.
