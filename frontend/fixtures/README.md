# API fixtures

Recorded responses from the real dashboard, so the frontend can be developed
without the backend.

The backend needs 140 MB of producer CSVs, a 30 MB foundry DuckDB and a live
av-gateway, all of which exist only on the deployment box. None of that is what
a React change is about. These files are what each screen actually received on
**2026-09-01**, captured by `scripts/capture_api_fixtures.py`.

```bash
cd frontend
npm run dev:fixtures     # serves fixtures/api instead of proxying to :8010
npm run dev              # unchanged: proxies /api to a real backend on :8010
```

## What is in here

180-odd JSON files under `api/`, laid out by URL, plus `api/index.json` — the
manifest that maps each recorded request to its file. About 14 MB.

The slice is the newest **10 trading days** (2026-08-20 … 2026-09-02) and the
**20 most-signalled tickers** in that window. Every screen has something real on
it: overview, runs, analytics, explore, LSTM windows, per-day pages, the score
browser, ticker pages with intraday charts, and signal detail panels.

## How a request is answered

`plugin.js` matches on the path plus a normalised query string, so parameter
order does not matter. Then:

- **exact** — the request was recorded. Response header `x-fixture-match: exact`.
- **fallback** — nothing matched, so the same path's least-parameterised
  capture is served, with `x-fixture-match: fallback` and a line in the vite
  terminal. This is a filter combination nobody recorded: **the data is real,
  the filters are the recorded ones rather than the ones you selected.** Sorting
  and paging past the recorded offsets behave the same way.
- **computed** — only `/api/tickers`. The header search types a character at a
  time, so its queries cannot be enumerated; it is answered by running the same
  substring match as `Store.search_tickers` over every ticker the captures
  mention.
- **404** — `/api/signal?id=` for an uncaptured id, and any path not recorded at
  all. Signal detail deliberately refuses to fall back: showing a neighbouring
  signal in the panel would look right and be wrong.

`POST /api/feedback` gets a canned receipt. There is no sign-in in fixtures
mode — the gate is backend middleware, and there is no backend.

Error responses are recorded too, and replayed with their status rather than
flattened to a 200 — an intraday chart for a symbol the gateway has no
continuity basis for really does answer `502 intraday data unavailable`, and
the UI has to render that. The current set happens to be all 200s; when a
recording does capture one, the recorder prints it at the end, and
`jq '.responses[] | select(.status != 200)' api/index.json` lists them.

## Re-recording

On the box with the data:

```bash
.venv/bin/python scripts/capture_api_fixtures.py          # same 10 × 20 slice
.venv/bin/python scripts/capture_api_fixtures.py --days 20 --tickers 40
```

It takes about ten minutes, nearly all of it waiting for both price books to
build — capturing before they land records a dashboard of nulls that reads as a
frontend bug forever after. The script is read-only against every producer.

A new endpoint, or a filter worth having a real response for, goes in
`list_specs()` in that script. The dev server picks up a re-recorded manifest
without a restart.

## Derived responses

Five entries in `api/index.json` carry `"derived": true`, and every one of them
is a `/api/lab` response under `api/lab/`. They were **not** produced by a
capture run: `/api/lab` did not exist yet the last time the recorder had a box
with the producer data, and without them the vector lab cannot render off
fixtures at all. Their shape and their producer notes are taken from
`LAB_PRODUCERS` and `lab_slice` in `backend/main.py`, so they match the contract
the API states — but the numbers in the LSTM slices are derived from the
recorded signal set, not measured by the backend.

Do not reason about lab data from them. The specs are already registered in
`list_specs()`, so the next real run on the data box overwrites all five and the
flag should be dropped with it. Nothing else in this set is derived; the flag
exists so that stays checkable:

```bash
jq '.responses[] | select(.derived)' api/index.json
```
