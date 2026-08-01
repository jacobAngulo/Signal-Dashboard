# Signal-Dashboard

Standalone read-only analytics UI over LSTM + Intrinsic + Foundry signals.
See README.md for architecture, routes, and run instructions.

Rules:

- **Strictly read-only** against the producer repos' outputs. This
  repo must never write into the other projects.
- **Decoupled from execution systems by design** (Jacob's call, 2026-07-06):
  no execution DB, execution API, or bot state. Signal "status" is
  price-performance based (up/down/pending since signal). Don't re-add execution
  coupling without being asked.
- Daily performance prices come from av-gateway `POST /continuous-ohlcv/bulk`
  (policy `dashboard`). Ticker-chart intraday prices come from gateway-owned
  `/market-data/intraday`, use Alpaca IEX raw bars transformed by the same
  dashboard corporate-action policy, and never enter performance calculations.
  Ticker pages expose independent lookback, bar interval, and visualization
  controls. Historical `observed` actions are compact `CA` audit flags:
  same-continuity-segment returns are valid, while boundary-crossing windows,
  conflicts, unsupported states, and coverage failures remain fail-closed.
  Producer CSV prices survive only as `signal_price`, never as a fallback.
  **Entry anchors at the signal, not the actionable
  session** (Jacob's call, 2026-07-13): close of the last session at/before
  the signal — for foundry, strictly before its actionable `date`, so
  `ret_since` includes the overnight gap the event traded on. The
  actionable-session view is kept alongside (`ret_1d/5d/20d`,
  `ret_since_actionable`, `actionable_entry_px`) and stays pending until that
  session trades. The Trend spark is pure ticker data and renders whenever
  the gateway has bars.
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
