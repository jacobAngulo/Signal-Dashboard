# Signal Dashboard

Standalone, read-only analytics UI over the **LSTM_AI_Stock_Predictor**,
**Intrinsic-Value-Monitor**, and **Signal-Foundry** signal producers. Decoupled
from execution systems — it only exposes what the producers generated and how
it moved.

Answers:

1. **What was generated, when, with what?** Every producer run (status,
   score row counts, staleness, generated-at), with drill-down from a
   calendar heatmap into per-day pages and the full ~1.3k-row score files.
2. **How are past signals doing?** Every BUY gets forward returns
   (1d / 5d / 20d / since-signal) and an up/down/pending status, computed
   from corporate-action-aware continuous gateway prices, anchored to each
   signal's causal entry session. Tickers outside price coverage get
   an explicit `no_px` status instead of an eternal "pending".
3. **Is the signal any good?** Analytics: win rates by horizon, signal
   strength vs outcome scatter, signal-vs-universe metric distributions,
   quartile buckets, cumulative take-every-BUY curves, weekday effects.

## Foundry events are trading-day aligned and gated

Foundry emits events around the clock; the daily producers emit one batch per
trading day. To live on the same calendar, each foundry event is bucketed by
the **trading day it is actionable for** using causal `extracted_at`, not a
historical publication date. Extraction timestamps convert to ET; anything
at/after 16:00 ET (and weekends/holidays) rolls to the next session. The raw
publish timestamp stays on the row (`published_at`, `event_date`) as source
context, while `as_of_timestamp` records actual extraction availability. The
overview card also surfaces the fetch/extract loop health
(queue depth, per-source freshness) straight from the foundry DB, since a
silent source otherwise looks like a quiet news day.

**One signal per ticker per trading day.** All of a ticker-day's events roll
up into a single decision row (contributing events are listed in the detail
drawer). Extracted sentiment alone never triggers a BUY/SELL: direction
weight is `signal_score × |sentiment|`, and the gate (`foundry_gate` in
config.json) requires either one event past `score_floor` (in practice a
primary-source EDGAR filing the LLM scored with conviction) or ≥2 aligned
events whose net weight passes `net_floor`, with a `dominance` share that
turns mixed-direction chatter days into WATCH. Every row carries a
`gate_reason` explaining the outcome.

## Attention and coverage states

The production BUY/SELL contracts remain unchanged. Additive WATCH rows expose
the tested research candidates: LSTM `p > 0.18` with a 1.5x prior-volume surge,
Intrinsic's shadow-only `0.075-0.65` ratio extension, and Foundry's fixed top-five
event-type-prior queue. Score browsers retain the underlying attention/shadow
columns. Run rows also merge each producer's coverage manifest, including ready
counts, ready fractions, valuation readiness, and fail-closed guard status.

## Navigation model

Hash-routed and deep-linkable: `#/` overview · `#/explore` server-filtered,
paginated signal explorer · `#/lstm-windows` all published above-threshold
LSTM candidates grouped by each ticker's strongest horizon/day, with the final
daily pick highlighted · `#/analytics` · `#/runs` ·
`#/scores/<producer>/<date>` curated raw score browser · `#/ticker/<T>`
per-ticker page (default 5-day/5-minute Alpaca IEX candlesticks with independent
lookback, 1m/5m/15m/1h/1D bar interval, Candles/OHLC/Line/Area style controls,
volume, timestamped signal markers, non-blocking descriptive insights, metric
history, and all signals) ·
`#/day/<date>` per-day page. Every ticker and date anywhere in the UI is a
link; the header has jump-to-ticker search.

Price snapshots refresh asynchronously every five minutes by default
(`price_refresh_seconds` or `PRICE_REFRESH_SECONDS`). Unresolved corporate
actions remain visible as compact `CA` flags: chart/model/signal insights still
render, same-basis post-action returns remain usable, and only return windows
that cross uncertain action evidence are excluded. Analytics eligibility is
evaluated separately for each return horizon rather than dropping the signal.
Intraday chart requests use a separate 45-second gateway cache and never alter
the daily SIP performance book.

## Frontend development without the backend

The API needs the producers' 140 MB of CSVs, the 30 MB foundry DuckDB and a
live av-gateway, none of which exist off the deployment box. So the responses
every screen loads are recorded into `frontend/fixtures/api` and committed — a
10-day, 20-ticker slice, about 14 MB:

```bash
cd frontend
npm run dev:fixtures     # recorded responses, no backend, no sign-in
npm run dev              # proxies /api to a real backend on :8010
```

Requests match exactly where they were recorded and fall back to the same
endpoint's default capture otherwise, which the `x-fixture-match` header and
the vite log report so an unhonoured filter is never mistaken for a real one.
Re-record with `.venv/bin/python scripts/capture_api_fixtures.py` on a box that
has the data. See `frontend/fixtures/README.md`.

## Access

Every route requires a Google sign-in. The check is a single middleware in
front of the application rather than a dependency on each route, so a route
added later is closed unless someone deliberately opens it;
`auth.PUBLIC_PATHS` is the complete list of exceptions and
`tests/test_auth_gate.py` walks the real route table to keep it honest.

Authorization is one environment variable:

```text
AUTH_ALLOWED_EMAILS=someone@example.com,someone-else@example.com
```

There is no sign-up and no request queue — a verified Google account that is
not on the list gets nothing. An empty list means nobody, not everybody: a
process that starts without credentials or without a list refuses every
request and says so on the login page, because the opposite failure mode
publishes the dashboard.

Reachable today over the admin WireGuard tunnel at
`https://angulo-solutions.com/signal-dashboard/`. The sign-in is a second,
independent layer rather than a replacement for that.

## Architecture

- `backend/` — FastAPI (port 8010). Reads producer outputs strictly read-only:
  LSTM/Intrinsic `signals/` dirs plus Signal-Foundry's DuckDB file. It caches in
  memory and auto-reloads when source files change (mtime fingerprints). Serves
  the built frontend. `GET /api/signals` is a filterable, optionally paginated
  JSON feed; list rows use a compact contract and `GET /api/signal?id=...`
  exposes full detail on demand.
- `frontend/` — React 18 + Vite + recharts, tiny hash router (no deps).
- `backend/auth.py` — the sign-in gate. Shared primitives (state/nonce/PKCE,
  ID-token verification, session store) come from `ops_kit.web_auth` via the
  `ops-kit[web-auth]` extra; only the policy lives here.
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

Sign-in needs `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, and `AUTH_ALLOWED_EMAILS`
in `.env.local` (mode 0600, gitignored). Without them the app starts and
refuses every request — check `GET /api/auth/status`, which stays reachable
precisely so an unreachable dashboard is still diagnosable.

Deploy:

1. `useradd --system --no-create-home --shell /usr/sbin/nologin signal-dashboard`
2. `mkdir -p /srv/data/signal-dashboard/db` and `chown` it, plus `.env.local`,
   to that user.
3. `cp deploy/signal-dashboard.service /etc/systemd/system/ && systemctl enable --now signal-dashboard`
4. Merge `deploy/nginx-location.conf` into the private-plane server block. The
   `X-Forwarded-Prefix` header in it is required, not decorative — without it
   the login redirect and the OAuth callback URL both come out wrong.
