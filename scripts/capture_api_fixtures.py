"""Record the dashboard's API responses as frontend development fixtures.

Frontend work needs the shape of a real response, not the producers behind it.
Reproducing the backend locally means 140 MB of producer CSVs, a 30 MB foundry
DuckDB and a live av-gateway; none of that is available off this box, and none
of it is what a React change is actually about. So this script drives the real
app once, against the real data, and writes what each screen received to
`frontend/fixtures/api/`. `npm run dev:fixtures` then serves those files in
place of the backend (see `frontend/fixtures/plugin.js`).

Scope is deliberately a slice, not the archive: the newest `--days` trading
days and the `--tickers` most-signalled symbols inside that window. TB-59 fixed
those at 10 and 20, which keeps the whole set small enough to live in git.

What is recorded is what the frontend actually asks for. Every request below is
the literal path and query string a view builds -- `views/Explore.jsx` opens
with `buys_only=true&exit_window=20&limit=75...`, so that is the key recorded,
and the dev server can answer it exactly. Filter combinations nobody captured
fall back to the same path's default capture, which is why the fallback exists
rather than a 404: a fixture set cannot enumerate a filter space.

Run it from the repo root with the app's own venv, on the box that has the
data:

    .venv/bin/python scripts/capture_api_fixtures.py

It is read-only against every producer, like the rest of this repo. The only
thing it writes is the fixture tree.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "frontend" / "fixtures" / "api"
PRODUCERS = ("lstm", "intrinsic", "foundry")

# Every letter, so the header's jump-to-ticker search behaves like a search
# rather than a lookup table with twenty entries in it.
SEARCH_PREFIXES = tuple("abcdefghijklmnopqrstuvwxyz")


def normalize(params):
    """The query string as the frontend's `api()` helper would send it.

    `frontend/src/api.js` drops undefined/null/empty values and leaves the rest
    to URLSearchParams. Sorting on top of that gives one stable key per request
    regardless of the order a view happened to build its object in; the dev
    server normalizes incoming requests the same way.
    """
    if not params:
        return ""
    pairs = [
        (str(k), str(v))
        for k, v in params.items()
        if v is not None and v != ""
    ]
    return urlencode(sorted(pairs))


def request_key(path, params=None, method="GET"):
    path = "/" + path.strip("/")
    qs = normalize(params)
    return f"{method} {path}?{qs}" if qs else f"{method} {path}"


class Spec:
    """One recorded request: where to ask, and what to call the file."""

    def __init__(self, name, path, params=None, *, optional=False):
        self.name = name              # fixture file, relative to the out dir
        self.path = "/" + path.strip("/")
        self.params = params or {}
        # Optional captures are allowed to 404 -- a producer that published no
        # score file for a date is data, not a broken capture.
        self.optional = optional

    @property
    def key(self):
        return request_key(self.path, self.params)

    @property
    def url(self):
        qs = normalize(self.params)
        return f"{self.path}?{qs}" if qs else self.path


def slug(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-") or "x"


# --------------------------------------------------------------- the app

def load_app():
    """Import the real app with the session gate lifted.

    The gate is one middleware in front of everything (`backend/main.py:30`),
    so a capture would otherwise record twelve identical 401s. Removing that
    one entry is honest about what is being bypassed -- far better than minting
    a session, and it cannot leak into the served app, which imports its own
    process.
    """
    from backend import auth, main

    before = len(main.app.user_middleware)
    main.app.user_middleware = [
        m for m in main.app.user_middleware
        if getattr(m, "kwargs", {}).get("dispatch") is not auth.require_session
    ]
    removed = before - len(main.app.user_middleware)
    if removed != 1:
        raise SystemExit(
            f"expected to lift exactly one session middleware, lifted {removed}. "
            "The gate moved; fix this script rather than capturing 401s."
        )
    # Starlette caches the composed stack after the first request; it has not
    # been built yet here, but clear it so this is true whoever calls next.
    main.app.middleware_stack = None
    return main


def join_price_builds(store, deadline):
    for label, attr in (("decision", "_price_thread"),
                        ("candidate", "_candidate_price_thread")):
        thread = getattr(store, attr, None)
        if thread is None or not thread.is_alive():
            continue
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        print(f"  waiting for the {label} price book...", flush=True)
        thread.join(remaining)
        if thread.is_alive():
            print(f"  ! {label} price book still building; giving up on it",
                  file=sys.stderr)
            return False
    return True


def warm(store, timeout, *, retries=12, wait=30.0):
    """Load every producer, then settle both price books.

    Two things have to be true before a capture is worth keeping, and neither
    is true when `refresh()` returns.

    Foundry holds the DuckDB write lock through its fetch/extract cycle, and
    `FoundryData.load` answers a locked database by keeping what it already has
    (`backend/store.py:636`). In a fresh process that is nothing, so a capture
    taken during the cycle records a dashboard with a whole producer missing --
    which, months later, reads as a frontend bug rather than a bad snapshot. So
    wait for the lock rather than record around it.

    Then the price books, which build in background threads
    (`backend/store.py:1027`, `:1044`) and are the whole point of most of these
    screens. The decision book covers whatever universe the producers had when
    it started, so a foundry load that lands late changes the universe out from
    under it; refresh until the built inputs match the current ones.
    """
    started = time.time()
    deadline = started + timeout
    print("loading producers...", flush=True)

    missing = []
    for attempt in range(1, retries + 1):
        store.refresh()
        missing = [name for name, prod in store.producers.items()
                   if not getattr(prod, "dates", None)]
        if not missing:
            break
        if time.time() + wait > deadline:
            break
        print(f"  {', '.join(missing)}: nothing loaded (attempt {attempt}/{retries}). "
              f"Retrying in {wait:.0f}s -- foundry's fetch cycle holds the "
              "DuckDB write lock for a few minutes at a time.", flush=True)
        time.sleep(wait)
    if missing:
        raise SystemExit(
            f"producer(s) {', '.join(missing)} never loaded. Refusing to record "
            "a dashboard that is missing a producer: the fixtures would look "
            "complete and be wrong. Try again once the producer is readable."
        )

    for name, prod in store.producers.items():
        print(f"  {name}: {len(prod.dates)} days, {len(prod.decisions)} decisions",
              flush=True)

    # Settle the decision book against the final universe.
    for _ in range(3):
        store.refresh()
        if not join_price_builds(store, deadline):
            break
        if store._price_inputs() == store._price_inputs_built:
            break

    errors = [e for e in (store.price_load_error, store.candidate_price_load_error) if e]
    for err in errors:
        print(f"  ! price build reported: {err}", file=sys.stderr)
    if not store.prices:
        raise SystemExit(
            "no prices loaded. Every return, status and spark in the capture "
            "would be null. Check that av-gateway is reachable and retry."
        )
    print(f"  ready in {time.time() - started:.0f}s "
          f"({len(store.prices)} tickers priced)", flush=True)
    return errors


# ------------------------------------------------------------- selection

def pick_dates(store, n):
    return store.all_dates[-n:]


def pick_score_dates(store, n):
    """Each producer's own newest scored days, not the shared window's.

    The producers do not publish on the same calendar -- intrinsic's newest
    score file can be a fortnight behind foundry's, which emits daily. Slicing
    the shared window would leave that producer's tab with no fixture at all,
    and `views/Scores.jsx:39` opens each tab on that producer's newest scored
    date, so the tab would 404 on arrival.
    """
    dates = {}
    for name in PRODUCERS:
        producer = store.producers.get(name)
        available = sorted(getattr(producer, "scores", {}) or {})
        dates[name] = available[-n:]
    return dates


def pick_tickers(store, out_dir, dates, n):
    """The tickers a developer will actually click.

    Explore's first page is the list the app opens on, so its rows come first,
    in the order they appear: a working ticker page for row three is worth more
    than one for a heavily-signalled symbol nobody can see without scrolling.
    Ranking by signal count alone put six of that page's forty-four tickers in
    the set, so five clicks in six landed on a 404.

    Whatever is left over is filled by signal count inside the window, then by
    the wider index, so a thin window still produces `n` pages with something
    on them rather than an alphabetical run of empty ones.
    """
    picked = []
    seen = set()

    def take(ticker):
        if ticker and ticker not in seen:
            seen.add(ticker)
            picked.append(ticker)

    for name in ("signals/page-1.json", "signals/page-2.json"):
        path = out_dir / name
        if not path.exists():
            continue
        for row in json.loads(path.read_text()).get("signals", []):
            if len(picked) >= n:
                return picked
            take(row.get("ticker"))

    window = set(dates)
    counts = Counter()
    for row in store.all_decisions:
        if row.get("date") in window and row.get("ticker"):
            counts[row["ticker"]] += 1
    for ticker, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(picked) >= n:
            return picked
        take(ticker)

    for entry in sorted(store.ticker_index.values(),
                        key=lambda e: (-e["n_signals"], e["ticker"])):
        if len(picked) >= n:
            break
        take(entry["ticker"])
    return picked


# ---------------------------------------------------------------- specs

def list_specs(dates, score_dates):
    """Every list and aggregate request the frontend makes.

    Grouped by the view that issues it, with the parameters that view actually
    sends. Where a view has filter state, the default is captured plus the
    handful of variants worth clicking; the rest resolve to the default through
    the dev server's fallback.

    Captured before the ticker pages, because which ticker pages are worth
    having depends on which rows these lists came back with.
    """
    specs = []
    add = specs.append

    # App shell: the status pill, and the seed rows for the search index the
    # dev server computes from (`tickerIndex` in fixtures/plugin.js).
    add(Spec("health.json", "/api/health"))
    for prefix in SEARCH_PREFIXES:
        add(Spec(f"tickers/q-{prefix}.json", "/api/tickers", {"q": prefix}))

    # Overview and Runs take no parameters at all.
    add(Spec("overview.json", "/api/overview"))
    add(Spec("runs.json", "/api/runs"))

    # Analytics: no filters on open, then one capture per producer and one
    # windowed range, which is the control the view actually exposes.
    add(Spec("analytics.json", "/api/analytics"))
    for producer in PRODUCERS:
        add(Spec(f"analytics/{producer}.json", "/api/analytics",
                 {"producer": producer}))
    add(Spec("analytics/window.json", "/api/analytics",
             {"date_from": dates[0], "date_to": dates[-1]}))

    # Explore. The defaults here are `views/Explore.jsx:62` verbatim, including
    # the exit-rule parameters it sends even when no rule is set.
    explore = {
        "buys_only": "true", "limit": 75, "offset": 0,
        "spark": "true", "exit_window": 20, "trailing": "false",
    }
    add(Spec("signals/page-1.json", "/api/signals", explore))
    add(Spec("signals/page-2.json", "/api/signals", {**explore, "offset": 75}))
    for producer in PRODUCERS:
        add(Spec(f"signals/{producer}.json", "/api/signals",
                 {**explore, "producer": producer}))
    add(Spec("signals/all-decisions.json", "/api/signals",
             {**explore, "buys_only": "false"}))
    add(Spec("signals/window.json", "/api/signals",
             {**explore, "date_from": dates[0], "date_to": dates[-1]}))
    # One capture with a stop/target rule applied, so the simulated-exit
    # columns exist in the fixture set at all.
    add(Spec("signals/exit-rule.json", "/api/signals",
             {**explore, "stop_pct": 0.05, "target_pct": 0.1}))

    # LSTM windows (`views/LstmWindows.jsx:122`).
    windows = {"group_by": "horizon", "sort": "date", "dir": "desc",
               "limit": 100, "offset": 0}
    add(Spec("lstm-windows/default.json", "/api/lstm/windows", windows))
    add(Spec("lstm-windows/page-2.json", "/api/lstm/windows",
             {**windows, "offset": 100}))
    add(Spec("lstm-windows/by-date.json", "/api/lstm/windows",
             {**windows, "group_by": "date"}))
    add(Spec("lstm-windows/picks-only.json", "/api/lstm/windows",
             {**windows, "picks_only": "true"}))
    add(Spec("lstm-windows/resolved-only.json", "/api/lstm/windows",
             {**windows, "resolved_only": "true"}))

    # The vector lab (`views/Lab.jsx`). Its `where` predicates are a repeated
    # query parameter over an open field space, which no capture can enumerate
    # -- so these record the page's opening request and one alternate measure,
    # and a slice with facets applied falls back to the unfiltered capture with
    # `x-fixture-match: fallback`, the same as every other filter combination
    # in this set. `limit=1` is what the page actually asks for until the rows
    # panel is opened: the cards are computed over the whole slice server-side
    # and do not need the rows.
    lab = {"producer": "lstm", "outcome": "ret_5d", "buckets": 5,
           "min_bucket": 20, "sort": "date", "dir": "desc",
           "limit": 1, "offset": 0}
    add(Spec("lab/lstm.json", "/api/lab", lab))
    # `ret_5d` is still pending for most of a ten-day slice, and a fixture set
    # where every average is blank teaches the wrong lesson about the page.
    add(Spec("lab/lstm-since-signal.json", "/api/lab",
             {**lab, "outcome": "ret_since"}))
    # With the rows panel open, so the table has something to render.
    add(Spec("lab/lstm-rows.json", "/api/lab", {**lab, "limit": 100}))
    # The producers that are not wired up yet answer with their reason rather
    # than a slice. Recorded so the placeholder renders off fixtures, and so a
    # producer becoming available shows up here as a changed capture.
    for name in ("intrinsic", "foundry"):
        add(Spec(f"lab/{name}.json", "/api/lab", {**lab, "producer": name}))

    # Day pages follow the shared calendar the heatmap links into.
    for date in dates:
        add(Spec(f"day/{date}.json", f"/api/day/{date}"))

    # The score browser follows each producer's own publishing calendar.
    for producer, producer_dates in score_dates.items():
        for date in producer_dates:
            add(Spec(f"scores/{producer}/{date}.json",
                     f"/api/scores/{producer}/{date}",
                     {"dir": "desc", "limit": 100, "offset": 0}))

    return specs


def ticker_specs(tickers):
    """Ticker pages: the page, its default chart, and one alternate interval.

    The search captures for these symbols ride along here so that typing a
    captured ticker in full reaches a page that exists.
    """
    specs = []
    add = specs.append
    for ticker in tickers:
        add(Spec(f"tickers/q-{slug(ticker.lower())}.json",
                 "/api/tickers", {"q": ticker}))
        add(Spec(f"ticker/{ticker}.json", f"/api/ticker/{ticker}",
                 {"exit_window": 20, "trailing": "false"}))
        # Charts are the one place the gateway can fail-close on a symbol it
        # has no continuity basis for; that 502 is real data, so it is recorded
        # rather than treated as a broken capture.
        add(Spec(f"ticker/{ticker}/chart-5Min-5D.json",
                 f"/api/ticker/{ticker}/chart",
                 {"interval": "5Min", "window": "5D"}, optional=True))
        add(Spec(f"ticker/{ticker}/chart-1Hour-1M.json",
                 f"/api/ticker/{ticker}/chart",
                 {"interval": "1Hour", "window": "1M"}, optional=True))
    return specs


def signal_specs(client, out_dir, limit):
    """Detail captures for the signals the recorded lists can actually open.

    `SignalDetail.jsx` fetches `/api/signal?id=<id>` for whatever row was
    clicked, so the ids have to come from the pages already recorded rather
    than from a guess. The dev server refuses to substitute a neighbouring
    signal for an uncaptured id, which makes coverage here worth paying for:
    the default covers both recorded Explore pages before it spends anything
    on the variant lists.
    """
    ids, seen = [], set()
    for name in ("signals/page-1.json", "signals/page-2.json",
                 "signals/all-decisions.json", "signals/lstm.json",
                 "signals/intrinsic.json", "signals/foundry.json"):
        path = out_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        for row in payload.get("signals", []):
            sig_id = row.get("id")
            if sig_id and sig_id not in seen:
                seen.add(sig_id)
                ids.append(sig_id)
    return [Spec(f"signal/{slug(i)}.json", "/api/signal", {"id": i})
            for i in ids[:limit]]


# --------------------------------------------------------------- capture

def capture(client, specs, out_dir):
    records, failures = [], []
    written = set()
    for i, spec in enumerate(specs, 1):
        # Signal ids are colon-delimited and become filenames by substitution,
        # so a collision is unlikely but would silently drop a capture.
        if spec.name in written:
            failures.append((spec, f"two requests want the file {spec.name}"))
            continue
        written.add(spec.name)
        try:
            response = client.get(spec.url)
        except Exception as exc:  # a route that raises is a finding, not a stop
            failures.append((spec, f"request raised: {exc}"))
            continue

        if response.status_code != 200 and not spec.optional:
            failures.append((spec, f"HTTP {response.status_code}"))
            continue
        if response.status_code == 404 and spec.optional:
            continue
        try:
            body = response.json()
        except ValueError:
            failures.append((spec, "response was not JSON"))
            continue

        target = out_dir / spec.name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(body, indent=1, sort_keys=False, ensure_ascii=False)
        target.write_text(text + "\n")
        records.append({
            "key": spec.key,
            "file": spec.name,
            "status": response.status_code,
            "bytes": len(text) + 1,
        })
        if i % 25 == 0 or i == len(specs):
            print(f"  {i}/{len(specs)} captured", flush=True)
    return records, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=10,
                        help="trading days to capture (default: 10)")
    parser.add_argument("--tickers", type=int, default=20,
                        help="ticker pages to capture (default: 20)")
    parser.add_argument("--signals", type=int, default=200,
                        help="signal detail captures (default: 200)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"fixture directory (default: {DEFAULT_OUT})")
    parser.add_argument("--price-timeout", type=float, default=900.0,
                        help="seconds to wait for the price books (default: 900)")
    parser.add_argument("--keep", action="store_true",
                        help="merge into the existing fixtures instead of "
                             "replacing them")
    args = parser.parse_args()

    main_mod = load_app()
    from fastapi.testclient import TestClient

    price_errors = warm(main_mod.STORE, args.price_timeout)
    store = main_mod.STORE

    dates = pick_dates(store, args.days)
    if not dates:
        raise SystemExit("no trading days loaded -- is the producer data readable?")
    score_dates = pick_score_dates(store, args.days)
    print(f"window {dates[0]}..{dates[-1]} ({len(dates)} days)", flush=True)
    for producer, producer_dates in score_dates.items():
        span = f"{producer_dates[0]}..{producer_dates[-1]}" if producer_dates else "none"
        print(f"  {producer} score files: {span}", flush=True)

    out_dir = args.out
    if out_dir.exists() and not args.keep:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(main_mod.app)

    # Lists first: they decide which ticker pages and signal details are worth
    # recording, so that the pages a developer can reach from the opening
    # screen are the pages that exist.
    specs = list_specs(dates, score_dates)
    print(f"capturing {len(specs)} list responses...", flush=True)
    records, failures = capture(client, specs, out_dir)

    tickers = pick_tickers(store, out_dir, dates, args.tickers)
    print(f"{len(tickers)} tickers: {', '.join(tickers)}", flush=True)
    pages = ticker_specs(tickers)
    print(f"capturing {len(pages)} ticker responses...", flush=True)
    more, more_failures = capture(client, pages, out_dir)
    records.extend(more)
    failures.extend(more_failures)

    details = signal_specs(client, out_dir, args.signals)
    if details:
        print(f"capturing {len(details)} signal details...", flush=True)
        more, more_failures = capture(client, details, out_dir)
        records.extend(more)
        failures.extend(more_failures)

    total = sum(r["bytes"] for r in records)
    manifest = {
        "generated_by": "scripts/capture_api_fixtures.py",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {"from": dates[0], "to": dates[-1], "dates": dates},
        "score_dates": score_dates,
        "tickers": tickers,
        "counts": {"responses": len(records), "bytes": total},
        "price_build_errors": price_errors,
        "responses": sorted(records, key=lambda r: r["file"]),
    }
    (out_dir / "index.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")

    print(f"\nwrote {len(records)} responses ({total / 1e6:.1f} MB) to {out_dir}")

    # Error responses are kept on purpose -- a ticker the gateway has no
    # continuity basis for really does answer 502, and the frontend has to
    # render that. Listing them keeps the difference between "recorded the
    # error" and "the capture broke" in front of whoever ran this.
    errored = [r for r in records if r["status"] != 200]
    if errored:
        print(f"\n{len(errored)} response(s) recorded a real error state:")
        for record in errored:
            print(f"  {record['status']}  {record['file']}")
    if failures:
        print(f"\n{len(failures)} request(s) did not record:", file=sys.stderr)
        for spec, why in failures:
            print(f"  {spec.url} -> {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
