# Progress

## 2026-07-30 - deployment migrated out of OpenClaw

- Moved the live checkout and Python environment to `/projects/Signal-Dashboard`.
  Updated producer/database paths and the systemd unit, added an explicit
  `av-gateway.service` dependency, and re-enabled the service for reboot.
  Verified `/api/health` and the Nginx `/signal-dashboard/` route from the new
  location.

## 2026-07-12 - additive attention tiers and causal Foundry dates

- Added backend-only support for LSTM attention and Intrinsic shadow rows as
  WATCH decisions. Existing BUY analytics and counts remain unchanged.
- Merged producer coverage manifests into Runs/API rows, including readiness,
  valuation coverage, and guard pass/fail fields.
- Foundry now uses `extracted_at` for actionable dates and `as_of_timestamp`,
  preserving publication date only as source context. Retrospective SEC
  backfill no longer appears as a causal historical signal.
- Added fixed top-five/day Foundry event-type attention ranks without changing
  directional gates. Dynamic score APIs expose all new fields, so no active
  frontend files needed modification.
- Validation: backend `py_compile` passed; 4 focused `unittest` cases passed;
  real-data refresh produced five Foundry attention rows for 2026-07-13 and
  kept LSTM/Intrinsic production decisions unchanged.

## 2026-07-07 — surface dropped-ticker staleness (ASTI report)

Jacob's report: ASTI's detail page has no recent history. Audit found the data
is genuinely absent — the producers stopped scoring ~2,550 tickers on 6/24
(universe collapse; root cause is an av-gateway filter vs Alpaca's
`overnight_tradable` rollout — documented, NOT fixed here per Jacob:
dashboard-only changes). ASTI itself was last scored 2026-05-22. The dashboard
now says so instead of silently truncating:

- `enrich()` adds `px_stale` (ticker's last price date < latest run date) and
  `/api/ticker/{t}` adds `last_scored` / `latest_run`.
- Ticker page: warning banner "Not scored since <date> — dropped out of the
  producers' universe; price line / since returns / status frozen as of that
  date". Price card labeled "producer pre-close snapshots (~12:15–12:30 PT),
  not official closes".
- SignalTable Since column and PerfTag get ⚠ + tooltip when `px_stale`;
  signal drawer's last-px stat shows "· stale ⚠".
- Deployed: `npm run build` + `systemctl restart signal-dashboard`; verified
  ASTI (stale, banner data 2026-05-22 vs run 2026-07-07), ASTC (current, no
  flags), and `px_stale` in /api/signals.

## 2026-07-06 — split per-producer scatters, signal creation times, PT display

Jacob's feedback: adj_prob and discount aren't comparable, so don't plot the
two producers on one metric axis; show when signals were created; display all
times in Pacific (he's in PST — the host VM is elsewhere, never trust its tz).

- Analytics: "Signal strength vs outcome" split into two charts (LSTM
  adj_prob / Intrinsic discount), each with its own x-axis and producer color
  (`charts.jsx` PerfScatter now takes a `producer` prop).
- `created_at` on every decision record, from the decision file's mtime (the
  CSVs only carry dates; mtime matches LSTM status `finished_at` to the
  second). Shown as a "Created (PT)" column in SignalTable and in the signal
  drawer. Run rows' `generated_at` falls back to the status file mtime, so
  Intrinsic (whose status JSON has no timestamp) now shows one too.
- All timestamps render in America/Los_Angeles (`format.js` fmtTs/fmtTime).
- Deployed: `npm run build` + `systemctl restart signal-dashboard`; verified
  created_at in /api/signals and new strings in the served bundle.

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
