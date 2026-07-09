# Signal-Dashboard

Standalone read-only analytics UI over LSTM + Intrinsic + Foundry signals.
See README.md for architecture, routes, and run instructions.

Rules:

- **Strictly read-only** against the producer repos' outputs. This
  repo must never write into the other projects.
- **Decoupled from Trading-Bot-Arena by design** (Jacob's call, 2026-07-06):
  no arena DB, no arena API, no execution/bot state. Signal "status" is
  price-performance based (up/down/pending since signal). Don't re-add arena
  coupling without being asked.
- Forward returns come from LSTM/Intrinsic daily score prices
  (`live_scores.close` / `intrinsic_scores.price`), not
  `shared_market_data/ohlcv` (stale between provisioning runs). Foundry events
  reuse those price series when a ticker/date overlaps.
- Foundry events are bucketed by the **trading day they're actionable for**
  (ET, ≥16:00 → next session, weekends/holidays roll forward, snapped to the
  LSTM/Intrinsic score-date calendar — see `_event_dates` in
  `backend/store.py`). Signals whose ticker can never get an entry price show
  status `no_px`, not `pending`.
- Foundry decisions are **one row per ticker per trading day**, gated by
  `_foundry_gate` (weights = signal_score × |sentiment|; single event needs
  `score_floor`, corroboration needs ≥2 aligned events past `net_floor`,
  mixed chatter fails `dominance` → WATCH; thresholds in config.json
  `foundry_gate`). Sentiment alone must never map straight to BUY/SELL
  (Jacob's call, 2026-07-09). Raw per-event rows stay in the foundry
  "scores" view.
- Deployed as systemd `signal-dashboard` on 127.0.0.1:8010, exposed at
  `/signal-dashboard/` via nginx. Backend changes need
  `systemctl restart signal-dashboard`; frontend changes need
  `cd frontend && npm run build` (FastAPI serves `dist/`).
- Frontend is hash-routed (`src/nav.js`) — new views must be reachable by
  URL, and tickers/dates rendered anywhere should use `TickerLink`/`DateLink`.
- Don't fabricate fields the source files don't have; if a view needs data
  that doesn't exist yet, surface "not available" instead.
