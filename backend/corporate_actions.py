"""Confirmed-continuity price book used by Dashboard performance analytics."""

from __future__ import annotations

import json
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .frames import records


POLICY = "dashboard"
SAFE_STATES = {"confirmed", "clear", "not_applicable"}


class HTTPGateway:
    """Small service client so Dashboard need not install av-gateway itself."""

    def __init__(self, url: str, *, timeout: float = 600.0):
        self.url = str(url).rstrip("/")
        self.timeout = float(timeout)

    def continuous_ohlcv_bulk(self, tickers, **params):
        payload = {
            "tickers": list(tickers),
            **{key: value for key, value in params.items() if value is not None},
        }
        request = Request(
            f"{self.url}/continuous-ohlcv/bulk",
            data=json.dumps(payload, default=str).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def intraday_ohlcv(self, ticker, **params):
        query = urlencode({
            "ticker": str(ticker).upper(),
            **{key: value for key, value in params.items() if value is not None},
        })
        request = Request(
            f"{self.url}/market-data/intraday?{query}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urlopen(request, timeout=min(self.timeout, 120.0)) as response:
            return json.loads(response.read().decode("utf-8"))

    def close(self):
        return None


def _blocked(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    text = str(value).strip()
    if not text or text in {"[]", "nan", "None"}:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return [text]
    return [str(item) for item in parsed] if isinstance(parsed, list) else [text]


def _frame(payload):
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, Mapping):
        return pd.DataFrame(payload.get("bars", payload.get("records", payload.get("data", []))))
    return pd.DataFrame(payload)


def _entry_index(rows, dates, entry_date, entry_snap):
    """Where a return/simulation window anchors, shared by `performance()` and
    `simulate_exit()` so the two can never disagree about the entry session.

    Returns `(index, blocked_reason)` -- `index` is None exactly when
    `blocked_reason` explains why (no coverage at all, the entry session
    hasn't traded yet, or it fell in an in-range gap that strict mode refuses
    to substitute for).
    """
    if not rows:
        return None, "no_gateway_price_coverage"
    if entry_snap == "before":
        i = bisect_left(dates, entry_date) - 1
    elif entry_snap == "on_or_before":
        i = bisect_right(dates, entry_date) - 1
    else:
        i = bisect_left(dates, entry_date)
        if i >= len(rows):
            # The entry session simply hasn't traded yet (latest-bucket
            # signals): distinct from an in-range gap.
            return None, "pending_entry_session"
        if dates[i] != entry_date:
            i = -1  # in-range gap: strict mode never substitutes a session
    if i < 0:
        return None, "missing_entry_session"
    return i, None


def _interval_guard(blocked_ids, unsafe, segments):
    """`blocked_reason` if the interval must fail closed, else None.

    Same semantics as `performance()`'s guard, extracted so the incremental
    walk in `simulate_exit()` and the one-shot check in `performance()` can
    never drift apart: coverage failures, hard-unsafe states, a boundary
    crossing with unresolved evidence, or unsafe metadata without ids all fail
    closed. An unresolved action only poisons a window when it crosses a
    continuity boundary -- once both endpoints share a post-action basis, the
    unknown constant adjustment cancels in the ratio.
    """
    coverage_ids = [
        action_id for action_id in blocked_ids
        if str(action_id).startswith("coverage:")
    ]
    hard_unsafe = [status for status in unsafe if status != "observed"]
    crosses_uncertain_boundary = len(segments) > 1 and bool(blocked_ids or unsafe)
    incomplete_unsafe_metadata = bool(unsafe and not blocked_ids)
    if coverage_ids or hard_unsafe or crosses_uncertain_boundary or incomplete_unsafe_metadata:
        return "corporate_action_unresolved"
    return None


class ContinuousPriceBook:
    def __init__(self):
        self.points = {}
        self.load_error = None
        # TB-46: stop/target simulations over the whole filtered Explore slice
        # can mean thousands of calls per request. Keyed on every argument
        # that changes the answer; cleared below whenever `points` is
        # replaced, so a refresh can never serve an exit computed against
        # retired prices.
        self._sim_cache = {}

    def load(self, gateway, tickers, *, start=None, end=None, chunk_size=100):
        symbols = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
        self.load_error = None
        if not symbols:
            self.points = {}
            self._sim_cache = {}
            return
        method = getattr(gateway, "continuous_ohlcv_bulk", None)
        if method is None:
            raise RuntimeError("continuous_ohlcv_bulk is required; producer-price fallback is forbidden")
        # The gateway computes continuity per ticker; a single request for the
        # whole universe cannot finish inside any sane client timeout. Bounded
        # chunks keep each request completable. The book still swaps in
        # all-or-nothing so a mid-load failure never yields a partial basis,
        # and the previous points keep serving until the swap: a full rebuild
        # takes minutes, so clearing up front would blank every request that
        # arrives while it runs.
        grouped = defaultdict(dict)
        step = max(int(chunk_size), 1)
        for offset in range(0, len(symbols), step):
            chunk = symbols[offset:offset + step]
            # The gateway is briefly unavailable while another producer takes
            # its consistent DuckDB snapshot. Resume the same all-or-nothing
            # build after that expected disconnect instead of throwing away
            # every completed chunk and waiting five minutes to start over.
            for attempt, delay in enumerate((2.0, 4.0, 8.0, None)):
                try:
                    payload = method(
                        chunk, start=start, end=end,
                        policy=POLICY, strict=False,
                    )
                    break
                except OSError:
                    if delay is None:
                        raise
                    time.sleep(delay)
            frame = _frame(payload)
            self._accumulate(frame, grouped)
        self.points = {
            ticker: [by_date[key] for key in sorted(by_date)]
            for ticker, by_date in grouped.items()
        }
        self._sim_cache = {}

    @staticmethod
    def _accumulate(frame, grouped):
        if frame.empty:
            return
        required = {
            "ticker", "date", "close", "action_revision", "price_basis",
            "continuity_segment", "security_id", "confirmation_status",
            "blocked_action_ids", "policy",
        }
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise RuntimeError(f"dashboard continuity response missing: {', '.join(missing)}")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date.astype(str)
        for row in records(frame):
            if str(row.get("policy")) != POLICY:
                raise RuntimeError(f"dashboard continuity response returned non-{POLICY} policy")
            try:
                price = float(row["close"])
            except (TypeError, ValueError):
                continue
            if not price > 0:
                continue
            ohlc = {}
            for key in ("open", "high", "low"):
                try:
                    value = float(row.get(key))
                except (TypeError, ValueError):
                    value = price
                ohlc[key] = value if value > 0 else price
            try:
                volume = float(row.get("volume"))
            except (TypeError, ValueError):
                volume = None
            if volume is not None and volume < 0:
                volume = None
            ticker = str(row["ticker"]).upper()
            grouped[ticker][row["date"]] = {
                "date": row["date"],
                "px": price,
                **ohlc,
                "close": price,
                "volume": volume,
                "action_revision": row.get("action_revision"),
                "price_basis": row.get("price_basis"),
                "continuity_segment": row.get("continuity_segment"),
                "security_id": row.get("security_id"),
                "security_identity": row.get("security_identity", row.get("security_id")),
                "confirmation_status": str(row.get("confirmation_status") or "").lower(),
                "blocked_action_ids": _blocked(row.get("blocked_action_ids")),
                "source_symbol": row.get("source_symbol", row.get("ticker")),
                "data_source": row.get("data_source"),
            }

    def series(self, ticker, start=None):
        rows = self.points.get(str(ticker).upper(), [])
        return [dict(row) for row in rows if start is None or row["date"] >= start]

    def performance(self, ticker, entry_date, *, sessions=None, through_last=False,
                    entry_snap=None):
        rows = self.points.get(str(ticker).upper(), [])
        dates = [row["date"] for row in rows]
        # entry_snap anchors the entry at the signal instead of an exact
        # session: "on_or_before" takes the last session <= entry_date (daily
        # producers score off that close), "before" the last session strictly
        # earlier (foundry events are actionable the session *after*
        # publication, so their signal-time price is the prior close).
        i, reason = _entry_index(rows, dates, entry_date, entry_snap)
        if i is None:
            result = {"return": None, "blocked_reason": reason}
            if rows:
                # The last point still serves the signal-independent columns
                # even when no entry session is available.
                result["last"] = rows[-1]
            return result
        j = len(rows) - 1 if through_last else i + int(sessions or 0)
        if j >= len(rows):
            return {
                "return": None,
                "blocked_reason": "pending_exit_session",
                "entry": rows[i],
                "last": rows[-1],
            }
        interval = rows[i : j + 1]
        blocked_ids = sorted({item for row in interval for item in row["blocked_action_ids"]})
        unsafe = sorted({
            row["confirmation_status"] for row in interval
            if row["confirmation_status"] not in SAFE_STATES
        })
        segments = []
        for row in interval:
            segment = row["continuity_segment"]
            if segment not in segments:
                segments.append(segment)
        action_warning_ids = [
            action_id for action_id in blocked_ids
            if not action_id.startswith("coverage:")
        ]
        if _interval_guard(blocked_ids, unsafe, segments):
            return {
                "return": None,
                "blocked_reason": "corporate_action_unresolved",
                "blocked_action_ids": blocked_ids,
                "action_warning_ids": action_warning_ids,
                "confirmation_status": unsafe[0] if unsafe else "unresolved",
                "entry": rows[i],
                "exit": rows[j],
                "last": rows[-1],
            }
        entry, exit_point = rows[i], rows[j]
        bases = sorted({str(row["price_basis"]) for row in interval})
        return {
            "return": exit_point["px"] / entry["px"] - 1.0,
            "blocked_reason": None,
            "blocked_action_ids": [],
            "action_warning_ids": [],
            "action_context_ids": action_warning_ids,
            "confirmation_status": unsafe[0] if unsafe else "confirmed",
            "price_basis": bases[0] if len(bases) == 1 else "+".join(bases),
            "continuity_segments": segments,
            "action_revision": max(
                (row["action_revision"] for row in interval if row["action_revision"] is not None),
                default=None,
            ),
            "entry": entry,
            "exit": exit_point,
            "last": rows[-1],
        }

    def simulate_exit(self, ticker, entry_date, *, stop=None, target=None,
                      max_sessions=20, side="long", entry_snap=None,
                      trailing=False):
        """Historical stop-loss/take-profit replay over already-stored prices.

        Read-only: this walks daily high/low bars that are already in the
        book and reports what would have happened, nothing more. No orders,
        no position state -- see CLAUDE.md and docs/TB-46-signal-windows-plan.md.

        Uses the same `_entry_index`/`_interval_guard` predicates as
        `performance()` so a simulated entry always lands on the identical
        session, and a window this dashboard would refuse to trust for an
        ordinary return is refused here too.
        """
        cache_key = (
            str(ticker).upper(), entry_date, stop, target,
            int(max_sessions), side, bool(trailing), entry_snap,
        )
        if cache_key in self._sim_cache:
            return self._sim_cache[cache_key]
        result = self._simulate_exit(
            str(ticker).upper(), entry_date, stop=stop, target=target,
            max_sessions=int(max_sessions), side=side,
            entry_snap=entry_snap, trailing=bool(trailing),
        )
        self._sim_cache[cache_key] = result
        return result

    def _simulate_exit(self, ticker, entry_date, *, stop, target, max_sessions,
                       side, entry_snap, trailing):
        rows = self.points.get(ticker, [])
        dates = [row["date"] for row in rows]
        out = {
            "outcome": None, "exit_date": None, "exit_px": None, "return": None,
            "sessions_held": None, "ambiguous": False, "stop_px": None,
            "target_px": None, "blocked_reason": None,
        }
        i, reason = _entry_index(rows, dates, entry_date, entry_snap)
        if i is None:
            out["blocked_reason"] = reason
            return out

        entry = rows[i]["px"]
        long_side = side != "short"
        if long_side:
            stop_px = entry * (1 - stop) if stop is not None else None
            target_px = entry * (1 + target) if target is not None else None
        else:
            # Foundry SELL rows: a short profits as price falls, so its stop
            # sits above entry and its target below.
            stop_px = entry * (1 + stop) if stop is not None else None
            target_px = entry * (1 - target) if target is not None else None
        out["stop_px"], out["target_px"] = stop_px, target_px

        def _return(exit_px):
            return exit_px / entry - 1.0 if long_side else 1.0 - exit_px / entry

        # The corporate-action guard is maintained incrementally across the
        # walk -- running sets/list, updated one bar at a time -- rather than
        # rebuilt over the whole interval each step, which would turn an O(n)
        # walk into O(n^2) over a slice of thousands of signals.
        blocked_ids, unsafe, segments = set(), set(), []

        def _absorb(row):
            blocked_ids.update(row["blocked_action_ids"])
            if row["confirmation_status"] not in SAFE_STATES:
                unsafe.add(row["confirmation_status"])
            segment = row["continuity_segment"]
            if segment not in segments:
                segments.append(segment)

        _absorb(rows[i])

        j = i
        limit = i + max_sessions
        while j < limit:
            j += 1
            if j >= len(rows):
                # Ran out of *data*, not out of window: the rule never got a
                # chance to fire. Distinct from "held", which means the window
                # completed and neither threshold was touched.
                out["outcome"] = "open"
                out["sessions_held"] = (len(rows) - 1) - i
                return out
            row = rows[j]
            _absorb(row)
            guard_reason = _interval_guard(blocked_ids, unsafe, segments)
            if guard_reason:
                # A window we cannot trust must not report a trigger, no
                # matter which bar the trigger appears to fall on.
                out["blocked_reason"] = guard_reason
                out["outcome"] = None
                return out
            if long_side:
                hit_stop = stop_px is not None and row["low"] <= stop_px
                hit_target = target_px is not None and row["high"] >= target_px
            else:
                hit_stop = stop_px is not None and row["high"] >= stop_px
                hit_target = target_px is not None and row["low"] <= target_px
            if hit_stop or hit_target:
                # Daily bars don't say which threshold traded first. Both in
                # one bar is measured at 0-0.5% of cases -- a footnote, not a
                # modelling choice -- and the conservative read is the loss.
                ambiguous = hit_stop and hit_target
                outcome = "stop" if (ambiguous or hit_stop) else "target"
                exit_px = stop_px if outcome == "stop" else target_px
                out.update({
                    "outcome": outcome,
                    "exit_date": row["date"],
                    "exit_px": exit_px,
                    "return": _return(exit_px),
                    "sessions_held": j - i,
                    "ambiguous": ambiguous,
                })
                return out
            if trailing and stop_px is not None:
                stop_px = (
                    max(stop_px, row["high"] * (1 - stop)) if long_side
                    else min(stop_px, row["low"] * (1 + stop))
                )
                out["stop_px"] = stop_px

        # The window completed with data available the whole way through, and
        # neither threshold fired -- exit at the close of the final session,
        # not the threshold price (there was no threshold event).
        exit_row = rows[j]
        out.update({
            "outcome": "held",
            "exit_date": exit_row["date"],
            "exit_px": exit_row["px"],
            "return": _return(exit_row["px"]),
            "sessions_held": j - i,
        })
        return out
