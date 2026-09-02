# TB-46 — Signal window + exit visibility

Implementation plan. Written to be executed start-to-finish by a coding agent
working in `/projects/Signal-Dashboard`. Every fact in "Ground truth" below was
verified against the live data on 2026-08-27 — **do not re-derive it**, build on
it.

Ticket: TB-46 "Signal window visibility" (Signal Dashboard, backlog).
Split-out ticket: **TB-57** (Signal Foundry) covers fixing `time_sensitivity`
itself. Do not do TB-57 work here.

---

## 0. Guardrails — read before touching anything

**The working tree is already dirty and that work is not yours.** `git status`
shows 8 modified files on `main` (an auth rework plus `SymbolLinks` in
`ui.jsx`/`TickerPage.jsx`). Two of them — `frontend/src/ui.jsx` and
`frontend/src/views/TickerPage.jsx` — are files this plan edits.

- Do **not** run `git checkout`, `git stash`, `git restore`, or `git reset`.
- Do **not** commit, branch, or push. Leave the tree dirty; Jacob ships from it.
- Edit around the existing changes. If an edit conflicts with uncommitted work,
  stop and report rather than reverting.

**Repo rules from `CLAUDE.md` that bind this work:**

1. Strictly read-only against producer outputs. Never write into
   `/srv/data/lstm`, `/srv/data/intrinsic`, or the foundry DuckDB.
2. Decoupled from execution systems. The stop/target feature is a **historical
   simulation over stored prices**, not an order engine, not a position book.
   No execution DB, no bot state.
3. Don't fabricate fields the source files don't have. If a producer has no
   window, the UI says so — it does not invent one.
4. All pandas values cross into the app through `backend/frames.py`. Use
   `records(frame)` and `sort_key()`. Never `DataFrame.to_dict("records")`.
5. Auth is one middleware in front of the whole app. You are adding **query
   parameters to existing routes**, not new routes — so `auth.PUBLIC_PATHS`
   must not change and `tests/test_auth_gate.py` must keep passing untouched.
6. Frontend is hash-routed; new state must be reachable by URL.

**Corporate-action discipline is the thing most likely to be got wrong.** The
existing `performance()` in `backend/corporate_actions.py:186` fails closed when
a return window crosses an uncertain action boundary. The new simulation must
use the *same* predicate, not a looser one. See Phase D.

---

## 1. Ground truth (verified — do not re-investigate)

### What each producer means by "window"

| Producer | Native field | Values | Real window? |
|---|---|---|---|
| **LSTM** (BUY rows) | `horizon` in `live_decision_*.csv` | `1d` `1w` `1m` `6m` | **Yes.** = 1, 5, 21, 126 XNYS sessions. The model predicts P(log return over that many sessions ≥ a per-ticker threshold). Source: `/projects/LSTM_AI_Stock_Predictor/TrainingData/lstm_v1_dataset.py:80-81`. |
| **LSTM** (WATCH/attention rows) | `attention_horizon_sessions` in `live_scores_*.csv` | `5.0` today | **Yes, and different.** The attention tier carries its own expected holding horizon ("Expected holding horizon metadata for attention candidates", `run_live_signals.py:561`). These rows also carry `best_horizon` (`6m`) — **that is the model's strongest head, not the attention window.** Use `attention_horizon_sessions` for WATCH rows. |
| **Intrinsic** | none | — | **No.** Daily valuation snapshot, no native horizon. Confirmed: no such column in either `intrinsic_decision_*.csv` or `intrinsic_scores_*.csv`. |
| **Foundry** | `time_sensitivity`, copied to `horizon` at `backend/store.py:790` | `intraday` `swing` `long_term` | **No usable one.** Categorical, no session count. 80% of signal rows say "swing"; it is near-deterministic given `event_type`; "swing" is also the pydantic default so a blank is indistinguishable from a real answer; it does not separate outcomes. That's TB-57. |

Session counts to hard-code (copy the numbers, **do not import from the LSTM
repo** — that would couple the repos):

```python
LSTM_HORIZON_SESSIONS = {"1d": 1, "1w": 5, "1m": 21, "6m": 126}
```

### What each producer means by "exit on its own signal"

| Producer | Native exit | Reality check |
|---|---|---|
| **LSTM** | entry session + N sessions | Computable. But LSTM has published **29 BUYs ever, 26 of them `6m`**, over 75 sessions of history — **zero have completed**. Expect "open" for nearly every row. That is correct output, not a bug. |
| **Intrinsic** | first later date the ticker's score status flips to `exit_candidate` (price ≥ intrinsic value, `/projects/Intrinsic-Value-Monitor/intrinsic/valuation.py:43`) | Computable from score history already in memory. **Zero of its 48 BUYs have ever triggered**, and it isn't a tracking gap — 46 are still scored daily and sit at `buy_candidate`. It buys at ≤50% of intrinsic value, so the stock must roughly double. Expect "open" everywhere. |
| **Foundry** | none | No native exit exists. Emit `None` and say so in the UI. Do not derive one from `time_sensitivity`. |

### Stop-loss / take-profit feasibility

- The price book **already stores daily open/high/low/volume per session**,
  corporate-action adjusted under the `dashboard` policy —
  `backend/corporate_actions.py:150-170`. Verified the gateway really returns
  them (not the close-fallback path).
- Same-bar ambiguity (both stop and target inside one daily bar) measured at
  **0–0.5%** across three threshold pairs on 389 long signals. Small enough to
  handle with a stated convention plus a flag.
- Reference numbers from the prototype, 20-session window, long side, foundry
  signals — use these to sanity-check your implementation:

| stop / target | target hit | stopped | ambiguous | neither |
|---|---|---|---|---|
| −5% / +10% | 17.7% | 59.1% | 0.3% | 22.9% |
| −3% / +6% | 24.4% | 61.7% | 0.5% | 13.4% |
| −10% / +20% | 12.3% | 34.4% | 0.0% | 53.2% |

You will not reproduce these exactly (the prototype used raw event rows, not
gated decisions, and no CA guard). Same ballpark = correct.

---

## 2. What we are building

**A.** A real **Window** column — honest per producer — in the shared signal
table, so it appears on Explore, the ticker page, Overview and Day pages at once.

**B.** A **native exit** readout: when the signal's own logic would have sold.

**C.** **Stop-loss / take-profit toggles in Explore** (the payoff feature): set
two percentages, see which signals would have hit the target, which got stopped
out, and which did neither — plus hit rates over the whole filtered slice.
Mirrored on ticker pages.

Priority if you run short: **C > A > B.** C is the one with real value today;
B will read "still open" for almost every row.

---

## Phase A — normalize the window (backend)

**File:** `backend/metrics.py`, inside `enrich()` (it already runs for every row
served, so every consumer gets the fields for free).

Add a module-level helper and call it from `enrich()`:

```python
LSTM_HORIZON_SESSIONS = {"1d": 1, "1w": 5, "1m": 21, "6m": 126}


def _window(rec):
    """Per-producer holding window, or None when the producer has none.

    Deliberately not unified into a single number: LSTM publishes a real
    session count, foundry publishes a word an LLM chose, intrinsic publishes
    nothing. Flattening those into one scale would be inventing data.
    """
```

Attach these fields to the enriched row:

| Field | LSTM BUY | LSTM WATCH | Intrinsic | Foundry |
|---|---|---|---|---|
| `window_label` | `"6m"` | `"5 sessions"` | `None` | `"swing"` |
| `window_sessions` | `126` | `5` | `None` | `None` |
| `window_basis` | `"producer_horizon"` | `"attention_horizon"` | `None` | `"llm_time_sensitivity"` |
| `window_note` | `"model horizon — 126 trading sessions"` | `"attention tier expected holding horizon"` | `"valuation snapshot — this producer publishes no holding window"` | `"the extraction model's own word (intraday/swing/long_term); not a session count — see TB-57"` |

Reading rules:

- LSTM BUY rows: `rec["horizon"]` → look up in `LSTM_HORIZON_SESSIONS`. Unknown
  value ⇒ label it verbatim, `window_sessions = None`. Never guess.
- LSTM WATCH rows: `rec["attention_horizon_sessions"]` (a float, e.g. `5.0`) →
  int. If missing/NaN, fall back to `best_horizon` via the map and set
  `window_basis = "producer_horizon"`.
- Foundry: `rec["horizon"]` (already `time_sensitivity`). Label verbatim.
- Intrinsic: all `None`.

Guard every read with the NaN discipline in `CLAUDE.md` — these values come from
CSV via `records()`, so a blank cell is `None`, but `attention_horizon_sessions`
is genuinely NaN on non-attention rows. Use `pd.isna()` / `math.isfinite`, not
truthiness.

**Also:** add `"best_horizon"` and `"attention_horizon_sessions"` to
`SIGNAL_SUMMARY_FIELDS` in `backend/main.py:38`? **No** — normalize in `enrich()`
and add only the `window_*` fields to the contract. Keeps the list contract about
what the UI renders, not about producer internals.

---

## Phase B — trading calendar

Needed only to name a **future** session date ("this 126-session window closes
on ..."). The app's existing calendar (`STORE.trading_calendar()`,
`backend/store.py:1050`) is *observed dates only* and cannot look forward.

1. Add to `requirements.txt`:

   ```
   # Forward trading-session arithmetic for signal windows and exit dates. The
   # app's own calendar is observed producer dates only, so it cannot name a
   # session in the future. Same pin as the LSTM repo uses, so the two agree
   # about what a session is without this repo importing that one.
   exchange-calendars==4.13.2
   ```

   Install with `.venv/bin/pip install -r requirements.txt`. (Verified
   downloadable from this box.)

2. New module `backend/trading_days.py` — **not** `calendar.py`, which shadows
   the stdlib:

   ```python
   def session_offset(date_str, n):    # -> "YYYY-MM-DD" | None
   def sessions_between(start, end):   # -> int | None  (exclusive of start)
   def is_session(date_str):           # -> bool
   ```

   - Build the calendar lazily once at first use, range roughly `2015-01-01`
     to `today + 3 years`, cached in a module global.
   - **Fail soft.** If the import or calendar build fails, every function
     returns `None` and the app still starts and serves. A missing exit *date*
     must never take the dashboard down — the window column and the session
     counts do not depend on it.
   - Keep the import inside the builder function so module import stays cheap.

---

## Phase C — native exits

**File:** `backend/metrics.py`, `enrich()`, after the window fields.

Fields to attach:

| Field | Meaning |
|---|---|
| `exit_basis` | `"sessions"` (LSTM) · `"producer_status"` (Intrinsic) · `None` (Foundry) |
| `exit_state` | `"closed"` · `"open"` · `None` when there is no native exit |
| `exit_date` | the session it closed on, or the projected close date; `None` if unknown |
| `exit_px` / `exit_return` | only when `exit_state == "closed"` |
| `sessions_elapsed` | sessions from entry to the last known close |
| `exit_note` | short human string for the tooltip |

**LSTM:** exit session = `entry_date` + `window_sessions`.

- Use `STORE.performance(ticker, date, sessions=window_sessions)`. It already
  returns `pending_exit_session` when the window hasn't completed — that maps
  straight to `exit_state = "open"`, and its `return`/`exit` map to
  `exit_return`/`exit_px` when it has.
- For the projected date when still open, use `trading_days.session_offset()`.
  `None` from it ⇒ omit the date, keep the counts.
- `sessions_elapsed` from `trading_days.sessions_between(entry_date, last_date)`,
  falling back to counting the price book's own points between the two dates
  (which is exact for the past and needs no dependency).

**Intrinsic:** first later date the ticker's status is `exit_candidate`.

Add a store helper next to the other convenience methods
(`backend/store.py`, after `trading_calendar()`):

```python
def producer_status_exit(self, producer, ticker, after_date, status):
    """First date > after_date on which `ticker` carried `status` in
    `producer`'s score history. Read-only over already-loaded history."""
```

`self.producers["intrinsic"].history[ticker]` is a list of dicts sorted by date
and already carries `status` (it's in `history_extra`, `backend/store.py:82`).
No file reads, no new I/O.

- Found ⇒ `exit_state = "closed"`, `exit_date` = that date, and compute
  `exit_return` with `STORE.performance(...)` anchored entry → that date.
- Not found ⇒ `exit_state = "open"`, `exit_note = "price has not reached
  intrinsic value yet"`.

**Foundry:** everything `None`, `exit_note = "this producer publishes no exit
signal"`. Do not synthesize one.

---

## Phase D — stop/target simulation

**File:** `backend/corporate_actions.py`, new method on `ContinuousPriceBook`.

### D1. Refactor first (do not skip)

`performance()` at line 186 opens with ~20 lines of entry-index snapping
(`entry_snap` = `"before"` / `"on_or_before"` / exact). The simulation needs
byte-identical behaviour. Extract it:

```python
def _entry_index(rows, dates, entry_date, entry_snap):
    """-> (index, blocked_reason). index is None when blocked."""
```

Call it from both. Also extract the corporate-action predicate so the two
cannot drift:

```python
def _interval_guard(blocked_ids, unsafe, segments):
    """-> blocked_reason | None. Same semantics as performance()'s guard:
    coverage failures, hard-unsafe states, a boundary crossing with unresolved
    evidence, or unsafe metadata without ids all fail closed."""
```

`performance()` must behave identically after the refactor —
`tests/test_corporate_action_performance.py` is the proof and must pass
unchanged.

### D2. The simulation

```python
def simulate_exit(self, ticker, entry_date, *, stop=None, target=None,
                  max_sessions=20, side="long", entry_snap=None,
                  trailing=False):
```

Returns:

```python
{
  "outcome": "target" | "stop" | "held" | "open" | None,
  "exit_date": str | None,
  "exit_px": float | None,
  "return": float | None,
  "sessions_held": int | None,
  "ambiguous": bool,          # stop and target inside the same daily bar
  "stop_px": float | None,
  "target_px": float | None,
  "blocked_reason": str | None,
}
```

Algorithm:

1. `i, reason = _entry_index(...)`; on a reason, return it with
   `outcome = None`.
2. `entry = rows[i]["px"]`. `stop_px = entry * (1 - stop)`,
   `target_px = entry * (1 + target)` for `side == "long"`; mirrored for
   `"short"` (foundry SELL rows — `1 + stop` / `1 - target`, and the triggers
   swap high/low).
3. Walk `j` from `i+1` while `j <= i + max_sessions`:
   - **Maintain the CA guard incrementally** — running sets of `blocked_ids`,
     `unsafe` statuses and `segments`, updated with `rows[j]`, then
     `_interval_guard(...)`. Accumulate; do not rebuild the interval each step
     (that turns an O(n) walk into O(n²)).
   - Guard trips ⇒ return `blocked_reason="corporate_action_unresolved"`,
     `outcome=None`. A window we cannot trust must not report a trigger.
   - `hit_stop = low <= stop_px`, `hit_target = high >= target_px` (long).
   - **Both in one bar** ⇒ `ambiguous = True`, resolve as `"stop"`. Daily bars
     don't say which came first; the conservative read is the loss. Measured at
     0–0.5% of cases, so this is a footnote, not a modelling choice worth
     agonising over.
   - Either alone ⇒ that outcome, exit at the threshold price (not the close —
     a stop fills at the stop), `sessions_held = j - i`.
   - `trailing=True` ⇒ after each bar, ratchet `stop_px` up to
     `max(stop_px, high * (1 - stop))` for longs. Only the stop trails; the
     target stays fixed.
4. Ran out of window with data still available ⇒ `outcome = "held"`, exit at
   `rows[i + max_sessions]` close, return computed.
5. Ran out of **data** before the window completed ⇒ `outcome = "open"`,
   `return = None`. **"held" and "open" are different answers** — one means the
   rule never fired, the other means we don't know yet. Never conflate them.

### D3. Caching

The Explore summary is computed over the *whole* filtered slice, which can be
thousands of rows. Add a plain dict cache on the book instance keyed by
`(ticker, entry_date, stop, target, max_sessions, side, trailing, entry_snap)`,
and **clear it in `load()` where `self.points` is swapped** — a stale cache
across a price refresh would serve exits computed from retired prices.

---

## Phase E — API

**File:** `backend/main.py`.

### `GET /api/signals` — new optional params

| Param | Type | Notes |
|---|---|---|
| `stop_pct` | `float`, `Query(None, gt=0, lt=1)` | e.g. `0.05` |
| `target_pct` | `float`, `Query(None, gt=0, lt=5)` | e.g. `0.10` |
| `exit_window` | `int`, `Query(20, ge=1, le=252)` | sessions to walk |
| `trailing` | `bool = False` | trailing stop |
| `sim_outcome` | `str = None` | filter to `target` / `stop` / `held` / `open` |

- **Only simulate when `stop_pct` or `target_pct` is given.** No params ⇒ zero
  extra work, byte-identical response to today.
- Simulate over the **full filtered slice** (before pagination) so the summary
  is honest, then paginate.
- Per row, attach `sim_outcome`, `sim_exit_date`, `sim_return`,
  `sim_sessions_held`, `sim_ambiguous`, `sim_blocked_reason`.
- Add all `window_*`, `exit_*` and `sim_*` names to `SIGNAL_SUMMARY_FIELDS`
  (`backend/main.py:38`) — the list contract is a whitelist, so a field not
  listed silently never reaches the browser. This is the single most likely
  cause of "I added it and nothing showed up".
- Extend `_slice_summary()` with a `sim` block when simulating: counts per
  outcome, `hit_rate` = target ÷ (target + stop), `avg_return`, `n_blocked`.

Pick the side per row: `side = "short" if row["decision"] == "SELL" else "long"`.
Use the same `entry_snap` rule as `enrich()` — `"before"` for foundry,
`"on_or_before"` otherwise — so simulated entries match the entry price already
shown in the table.

### `GET /api/ticker/{ticker}` (`backend/main.py:560`)

Accept the same five params and apply them to `sigs`, so the ticker page can
show the same simulated exits. Same "only when asked" rule.

---

## Phase F — frontend

### `frontend/src/SignalTable.jsx`

Two new columns, plus one conditional:

1. **`Window`** — after `Decision`. Renders `window_label` or a muted `n/a`;
   `title={window_note}`. Add `'window'` to the `hide` mechanism so Day/Overview
   can drop it if it crowds them.
2. **`Exit`** — after `Since`. `exit_state === 'closed'` ⇒ the date plus
   `<Pct v={exit_return} />`; `'open'` ⇒ muted `open · 51/126`; `null` ⇒ muted
   `–` with `title={exit_note}`.
3. **`Sim exit`** — only when any row carries `sim_outcome`. A `Tag` coloured
   `ok` for target, `err` for stop, `muted` for held/open, plus the date and
   `<Pct v={sim_return} />`. Show a `⚠` with a tooltip when `sim_ambiguous`, and
   the muted `CA` treatment when `sim_blocked_reason` is set — match how the
   existing `Since` column handles `px_stale`.

Remove the `horizon` suffix currently jammed into the Metric cell
(`SignalTable.jsx:64`) — the Window column replaces it.

### `frontend/src/views/Explore.jsx`

New **"Exit rules"** card in the left rail under "Filters":

- number inputs for stop % and take-profit % (accept `5` and `10`, send `0.05`
  and `0.10` — don't make Jacob type decimals),
- a sessions input (default 20),
- a "trailing stop" checkbox,
- a "clear" button, and a one-line explainer: *simulated on daily high/low
  prices — historical, not advice*.

Wire into the existing pattern exactly as the other filters are:
`useState` → the `history.replaceState` hash-param effect → the `api('signals', …)`
effect's dependency array → `reset()`. All four, or the control will silently
half-work. URL params: `stop`, `target`, `win`, `trail`.

Add the sim outcome counts to the **"Slice performance"** card when active:
target / stopped / neither, the hit rate, and average return at exit.

### `frontend/src/views/TickerPage.jsx`

Mind the uncommitted `SymbolLinks` edit here. Add a compact version of the same
Exit-rules control above the "Signals for X" card at line 163, feeding
`/api/ticker/{t}`. Reuse the Explore control by lifting it into
`frontend/src/ui.jsx` as `ExitRules` rather than copy-pasting.

### `frontend/src/SignalDetail.jsx`

Add `window` and `exit` to the `stat-row` at line 135, and add the new field
names to `CORE_KEYS` (line 8) so they don't also appear in the raw dump.

### `frontend/src/styles.css`

Reuse existing tag/muted classes. Only add new rules if the Exit-rules card
genuinely needs them. Mind the uncommitted diff here too.

---

## Phase G — tests

Existing suites must pass unchanged: `test_corporate_action_performance.py`
(proves the Phase D1 refactor was behaviour-preserving), `test_auth_gate.py`,
`test_frame_ingress.py`, `test_api_ux.py`, `test_store_attention.py`.

New `tests/test_exit_simulation.py`, using the fixture style already in
`test_corporate_action_performance.py` (synthetic bars, no network):

1. Long stop hit → outcome `stop`, exit at the stop price, correct
   `sessions_held`.
2. Long target hit → outcome `target`.
3. Both in one bar → `ambiguous is True` and outcome `stop`.
4. Neither, window completes → `held` with a real return.
5. Window runs past available data → `open`, `return is None`. (Explicitly
   assert this is **not** `held`.)
6. Window crosses an unresolved corporate action → `blocked_reason ==
   "corporate_action_unresolved"`, `outcome is None`.
7. A trigger that fires *before* the boundary is still reported — the guard is
   incremental, not window-wide.
8. Short side mirrors correctly.
9. Trailing stop ratchets and fires where a fixed stop would not.
10. `_entry_index` parity: for the same inputs, the entry chosen by
    `simulate_exit` equals the one `performance()` uses, across all three
    `entry_snap` modes.

New `tests/test_signal_windows.py`:

11. LSTM BUY `6m` → `window_sessions == 126`, basis `producer_horizon`.
12. LSTM WATCH → `window_sessions == 5` from `attention_horizon_sessions`,
    basis `attention_horizon` — **and not 126 from `best_horizon`**.
13. Intrinsic → all window fields `None`.
14. Foundry `swing` → label `"swing"`, `window_sessions is None`.
15. Unknown LSTM horizon string → label passes through, sessions `None`.
16. Intrinsic native exit: a synthetic history where the ticker flips to
    `exit_candidate` resolves `exit_state == "closed"`; one that never flips
    stays `"open"`.
17. `trading_days` fail-soft: with the calendar builder patched to raise, every
    function returns `None` and `enrich()` still produces rows.
18. Contract: with no sim params the `/api/signals` response contains no `sim_*`
    keys; with them, every row carries `sim_outcome`.

---

## Phase H — build, deploy, verify

```bash
cd /projects/Signal-Dashboard
.venv/bin/pip install -r requirements.txt      # picks up exchange-calendars
.venv/bin/python -m pytest tests -q            # all green before touching the service
cd frontend && npm run build && cd ..
systemctl restart signal-dashboard
```

Then verify against the real service (localhost API calls need no auth):

```bash
curl -s 'http://127.0.0.1:8010/api/signals?limit=3' | head -c 600
curl -s 'http://127.0.0.1:8010/api/signals?stop_pct=0.05&target_pct=0.10&limit=5' | head -c 900
curl -s 'http://127.0.0.1:8010/api/health'
```

Check by eye:

- Every row has a `window_label` or an explicit null — no `undefined`, no `NaN`.
- LSTM rows show `6m`; WATCH rows show 5 sessions; intrinsic rows show nothing;
  foundry rows show the LLM's word.
- Nearly all `exit_state` values are `"open"`. **That is the expected answer** —
  see Ground truth. If a pile of LSTM signals come back `"closed"`, the session
  arithmetic is wrong.
- With stop/target set, the outcome mix is in the ballpark of the table in
  Ground truth §1.
- `/api/health` still `ok`.

Report back: what you built, what the verification showed, and anything you hit
that this plan got wrong.

---

## Out of scope — do not do these

- **TB-57.** Do not touch `/projects/Signal-Foundry` — no prompt edits, no
  schema edits, no re-extraction.
- **Do not map `time_sensitivity` to session counts.** That's the whole point of
  the split.
- No order placement, position tracking, portfolio state, or P&L accumulation.
  This is a read-only historical view.
- No changes to auth, `PUBLIC_PATHS`, or the deploy manifest.
- No commits, branches, or pushes.
