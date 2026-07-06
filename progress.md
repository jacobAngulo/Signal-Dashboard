# Progress

## 2026-07-06 — decoupled from arena, explorable UI rebuild

Jacob's feedback: must be decoupled from Trading-Bot-Arena (signals only),
and the UI was too basic for digging.

- Removed all arena coupling: `backend/arena.py`, execution endpoint,
  traded/open/closed lifecycle, live Alpaca prices. Signal status is now
  price-based: up / down / flat / pending since signal.
- Backend additions: per-ticker score history (metric over time), ticker
  search index, signal-vs-universe metric histograms, metric-vs-return
  scatter data, weekday stats, per-signal sparkline series, day pages with
  top-of-score-file and prev/next.
- Frontend rebuilt around exploration: hash router (deep links, back/forward),
  global jump-to-ticker search, calendar heatmap of runs, pages — Overview,
  Explore (filter rail + slice summary), Ticker (price with signal markers +
  metric history charts), Day, Runs, Scores, Analytics (scatter, histograms,
  buckets, cumulative, weekday). Every ticker/date anywhere is a link;
  signal rows carry inline sparklines.

## 2026-07-05 — initial build

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
