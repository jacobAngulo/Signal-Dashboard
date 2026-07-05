# Signal-Dashboard

Read-only analytics UI over LSTM + Intrinsic signals and arena execution.
See README.md for architecture and run instructions.

Rules:

- **Strictly read-only** against the producer repos and `arena.sqlite3`
  (`mode=ro`). This repo must never write into the other projects.
- **P&L truth**: Alpaca (via the arena API `/api/positions`) is authoritative
  for live prices/unrealized P&L. sqlite-derived numbers are ownership-split
  approximations — keep them labeled as derived, never "improve" them into
  local P&L computation.
- Forward returns are computed from the producers' own daily score prices
  (`live_scores.close` / `intrinsic_scores.price`), not from
  `shared_market_data/ohlcv` (which goes stale between provisioning runs).
- Deployed as systemd `signal-dashboard` on 127.0.0.1:8010, exposed at
  `/signal-dashboard/` via the arena nginx server block. After frontend
  changes: `cd frontend && npm run build` (FastAPI serves `dist/`), no
  restart needed for static files; restart the service for backend changes.
- Don't fabricate fields the source files don't have; if a view needs data
  that doesn't exist yet, surface "not available" instead.
