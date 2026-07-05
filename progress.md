# Progress

## 2026-07-05 — initial build

- New repo. FastAPI backend (:8010) + React/Vite/recharts frontend.
- Data: LSTM + Intrinsic `signals/` dirs (decisions, full scores, premarket
  status JSONs, schema drift across May files handled), `arena.sqlite3`
  read-only (orders → FIFO round trips, open lots), arena API for live
  Alpaca prices (60s cache).
- Views: Today, Signals explorer (lifecycle status per signal + detail
  drawer with price spark + matched orders), Runs (+ day drill-down),
  Scores browser (server-side sort/pagination), Analytics (win rates by
  horizon, adj_prob/discount quartile buckets, cumulative equal-weight
  curves, best/worst), Execution (fleet ground truth).
- Deployed: systemd `signal-dashboard`, nginx at `/signal-dashboard/`.
- Known data nuances: LSTM flagship decisions are rarely the tickers bots
  buy (bot families trade score slices) — 0/37 direct matches vs 7/24 for
  intrinsic; premarket verifier can say NO_BUY while the preclose run later
  writes BUYs (both shown).
