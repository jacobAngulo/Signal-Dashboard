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


class ContinuousPriceBook:
    def __init__(self):
        self.points = {}
        self.load_error = None

    def load(self, gateway, tickers, *, start=None, end=None, chunk_size=100):
        symbols = sorted({str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()})
        self.load_error = None
        if not symbols:
            self.points = {}
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
        for row in frame.to_dict("records"):
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
        if not rows:
            return {"return": None, "blocked_reason": "no_gateway_price_coverage"}
        dates = [row["date"] for row in rows]
        # entry_snap anchors the entry at the signal instead of an exact
        # session: "on_or_before" takes the last session <= entry_date (daily
        # producers score off that close), "before" the last session strictly
        # earlier (foundry events are actionable the session *after*
        # publication, so their signal-time price is the prior close).
        if entry_snap == "before":
            i = bisect_left(dates, entry_date) - 1
        elif entry_snap == "on_or_before":
            i = bisect_right(dates, entry_date) - 1
        else:
            i = bisect_left(dates, entry_date)
            if i >= len(rows):
                # The entry session simply hasn't traded yet (latest-bucket
                # signals): distinct from an in-range gap, and the last point
                # still serves the signal-independent columns.
                return {"return": None, "blocked_reason": "pending_entry_session",
                        "last": rows[-1]}
            if dates[i] != entry_date:
                i = -1  # in-range gap: strict mode never substitutes a session
        if i < 0:
            return {"return": None, "blocked_reason": "missing_entry_session",
                    "last": rows[-1]}
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
        coverage_ids = [
            action_id for action_id in blocked_ids
            if action_id.startswith("coverage:")
        ]
        action_warning_ids = [
            action_id for action_id in blocked_ids
            if not action_id.startswith("coverage:")
        ]
        hard_unsafe = [
            status for status in unsafe
            if status != "observed"
        ]
        # An unresolved action poisons a return only when the requested window
        # crosses its continuity boundary. Once both endpoints are on the same
        # post-action basis, the unknown constant adjustment cancels in the
        # ratio. Coverage failures and malformed unsafe metadata still fail
        # closed because no trustworthy boundary is available.
        crosses_uncertain_boundary = len(segments) > 1 and bool(blocked_ids or unsafe)
        incomplete_unsafe_metadata = bool(unsafe and not blocked_ids)
        if (
            coverage_ids
            or hard_unsafe
            or crosses_uncertain_boundary
            or incomplete_unsafe_metadata
        ):
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
