# Signal-Dashboard

Standalone read-only analytics UI over LSTM + Intrinsic + Foundry signals.
See README.md for architecture, routes, and run instructions.

Rules:

- **Frontend UI changes must keep the static design catalog synchronized.**
  Follow `design/AGENTS.md`; update affected complete-screen and meaningful-state
  artifacts, their inventory, shared styles, and validation in the same change.

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
  `/signal-dashboard/` via nginx. Runs as the unprivileged `signal-dashboard`
  user; everything it reads is world-readable and the DuckDB handle is
  `read_only=True`, so it needs write access to nothing but
  `/srv/data/signal-dashboard`. Backend changes need
  `systemctl restart signal-dashboard`; frontend changes need
  `cd frontend && npm run build` (FastAPI serves `dist/`).
- **Frontend work does not need the backend.** `npm run dev:fixtures` serves
  the recorded API responses in `frontend/fixtures/api` (committed: a 10-day,
  20-ticker slice, ~14 MB) instead of proxying to :8010, so the UI runs off
  this box, where the producer data and the gateway do not exist. Re-record on
  a box that has them with `.venv/bin/python scripts/capture_api_fixtures.py`;
  add new endpoints to `list_specs()` there rather than hand-writing a JSON
  file, so what ships is always something the API actually returned. Fixture
  responses carry `x-fixture-match`: `exact`, or `fallback` when no capture
  matched the filters and the closest one was served instead.
- **Every route requires a Google sign-in** (`backend/auth.py`). The check is
  one middleware in front of the whole app, *not* a per-route dependency —
  `auth.PUBLIC_PATHS` is the complete list of what answers without a session,
  and `tests/test_auth_gate.py` walks the real route table and fails if
  anything else does. Add a route and it is closed by default; that is the
  point. Do not convert this to per-route `Depends`.
- **Authorization is `AUTH_ALLOWED_EMAILS` and nothing else** — a
  comma-separated list in `.env.local`. No sign-up, no request queue, no
  first-user-wins. Empty means nobody: if the process starts without
  credentials or without a list it refuses everyone and says so, because the
  alternative failure mode is publishing the whole dashboard.
- **Google OAuth client credentials are owned by Ops Console → Google Cloud**,
  not hand-edited. They live in `.env.local` (mode 0600, gitignored, owned by
  the service user), are declared in `deploy/manifest.toml` under
  `[google_auth]`, and are loaded via `EnvironmentFile=` in the unit. Rotate
  through that screen, which rewrites the file, restarts the unit, and can roll
  itself back. Since the credentials are now load-bearing for login rather than
  parked, a bad rotation locks people out — the VPN path at
  `angulo-solutions.com/signal-dashboard/` is the way back in.
- The OAuth callback URL is **built from the incoming request**, not
  configured, so the app can answer on more than one origin. Whatever it builds
  must appear verbatim in `redirect_uris` or Google returns
  `redirect_uri_mismatch`. The nginx `X-Forwarded-Prefix` header is what makes
  the prefixed form come out right — see `deploy/nginx-location.conf`.
- Shared sign-in primitives live in `ops_kit.web_auth` (the `ops-kit[web-auth]`
  extra), not in this repo: state/nonce/PKCE, ID-token verification, and the
  session store. Policy stays here. Do not fork them.
- Frontend is hash-routed (`src/nav.js`) — new views must be reachable by
  URL, and tickers/dates rendered anywhere should use `TickerLink`/`DateLink`.
- Don't fabricate fields the source files don't have; if a view needs data
  that doesn't exist yet, surface "not available" instead.
- **Pandas values cross into the app through `backend/frames.py`, always.**
  Use `records(frame)` instead of `DataFrame.to_dict("records")`: a blank CSV
  cell is NaN, NaN is truthy, so every `value or default` guard downstream
  passes it through until something compares it to a string and the request
  500s (TB-15). And use `sort_key()` for any `sort`/`max` over rows that come
  from more than one file or producer — ingress cleaning can't stop two
  producers writing the same column as text and as a number, and sorting is
  where that difference becomes an outage. `tests/test_frame_ingress.py`
  walks every producer spec and every sortable column, so a producer or
  column added later is covered by default.
