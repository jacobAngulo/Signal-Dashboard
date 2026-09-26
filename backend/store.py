"""Load and cache the Foundry producer's signals.

Reads are strictly read-only against the producer repos' data outputs.
Everything is cached in memory and reloaded when the source dirs change.
"""
from collections import defaultdict
import json
import math
import os
import re
import threading
import time
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import duckdb
except ImportError:  # pragma: no cover - exercised only in an incomplete env
    duckdb = None

from .config import (
    FOUNDRY_ATTENTION,
    FOUNDRY_DB,
    FOUNDRY_GATE,
    FOUNDRY_MODEL,
    FOUNDRY_PROMPT,
    PRICE_REFRESH_SECONDS,
)
from .corporate_actions import ContinuousPriceBook, HTTPGateway
from .config import AV_GATEWAY_URL
from .frames import records, sort_key

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Market timezone: foundry event timestamps are mapped to trading days in ET,
# matching the convention of Signal-Foundry's own backtest.
ET = ZoneInfo("America/New_York")

def clean(obj):
    """Recursively replace NaN/inf with None so responses are valid JSON."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if pd.isna(obj):
        return None
    return obj


def _file_fingerprint(path: Path):
    try:
        s = path.stat()
        return (s.st_mtime_ns, s.st_size)
    except FileNotFoundError:
        return ()


def _iso_ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    s = str(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return s


def _as_dt(v):
    """Parse to an aware datetime (naive values are taken as UTC)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _snap_trading(day, calendar):
    """First trading day at/after `day`. `calendar` is the sorted trading dates
    observed in producer score files; candidates beyond it (tonight's events
    for tomorrow's session) advance past weekends only."""
    iso = day.isoformat()
    if calendar:
        i = bisect_left(calendar, iso)
        # Snap forward only across a plausible weekend/holiday gap; a bigger
        # jump means the calendar simply doesn't cover this period.
        if i < len(calendar) and (
            datetime.fromisoformat(calendar[i]).date() - day).days <= 4:
            return calendar[i]
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def _event_dates(ts, calendar):
    """(event_date, trading_date) for an event timestamp, in market terms.

    Timestamped values convert to ET; published at/after 16:00 ET means the
    next session is the first one that can react. Date-only values (EDGAR
    backfill) carry no intraday time and are taken at face value. Either way
    the trading date lands on the daily producers' calendar, so foundry rows
    line up with the other producers' dates and price series.
    """
    s = "" if ts is None else str(ts).strip()
    if isinstance(ts, datetime) or len(s) > 10:
        dt = _as_dt(ts)
        if dt is None:
            return None, None
        loc = dt.astimezone(ET)
        event = day = loc.date()
        if loc.hour >= 16:
            day += timedelta(days=1)
    else:
        try:
            event = day = datetime.fromisoformat(s).date()
        except ValueError:
            return None, None
    return event.isoformat(), _snap_trading(day, calendar)


def _json_list(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def _foundry_gate(events, unknown_ticker):
    """Roll one ticker-day's events into a single decision.

    Extracted sentiment alone never triggers: direction weight is
    signal_score × |sentiment| (source quality, LLM confidence, novelty and
    sentiment strength all count), and a BUY/SELL needs either one event past
    `score_floor` (in practice a primary-source EDGAR filing) or aligned
    corroboration past `net_floor` — with `dominance` filtering out
    mixed-direction chatter days. Returns (decision, reason, w_pos, w_neg).
    """
    weight = lambda e: (e["signal_score"] or 0.0) * abs(e["sentiment"] or 0)
    pos = [e for e in events if (e["sentiment"] or 0) > 0]
    neg = [e for e in events if (e["sentiment"] or 0) < 0]
    w_pos = sum(weight(e) for e in pos)
    w_neg = sum(weight(e) for e in neg)
    gross = w_pos + w_neg
    if gross <= 0:
        return "WATCH", "no directional events", w_pos, w_neg
    if unknown_ticker:
        return ("WATCH", "not a currently-traded symbol — possible hallucination",
                w_pos, w_neg)
    dom = max(w_pos, w_neg) / gross
    if dom < FOUNDRY_GATE["dominance"]:
        return ("WATCH",
                f"mixed direction: {len(pos)} pos / {len(neg)} neg events, "
                f"{dom:.0%} dominance < {FOUNDRY_GATE['dominance']:.0%}",
                w_pos, w_neg)
    side, decision = (pos, "BUY") if w_pos > w_neg else (neg, "SELL")
    net = abs(w_pos - w_neg)
    top = max((e["signal_score"] or 0.0) for e in side)
    if top >= FOUNDRY_GATE["score_floor"]:
        return (decision,
                f"high-conviction event: score {top:.2f} ≥ "
                f"{FOUNDRY_GATE['score_floor']:.2f}", w_pos, w_neg)
    # Corroboration means corroboration: a single event only ever triggers
    # via score_floor, no matter how strong its sentiment.
    if len(side) >= 2 and net >= FOUNDRY_GATE["net_floor"]:
        return (decision,
                f"corroborated: {len(side)} aligned events, net weight "
                f"{net:.2f} ≥ {FOUNDRY_GATE['net_floor']:.2f}", w_pos, w_neg)
    return ("WATCH",
            f"below conviction floor: top score {top:.2f} < "
            f"{FOUNDRY_GATE['score_floor']:.2f}"
            + (f", net weight {net:.2f} < {FOUNDRY_GATE['net_floor']:.2f}"
               if len(side) >= 2 else " (single event)"), w_pos, w_neg)


def _foundry_type_group(value):
    event_type = str(value or "other").strip().lower()
    priors = FOUNDRY_ATTENTION.get("type_priors") or {}
    return event_type if event_type in priors else "other"


def _assign_foundry_attention(decisions):
    """Assign fixed-budget non-directional ranks to causal ticker-day rows."""
    priors = {
        "earnings": 0.356855,
        "mna": 0.193548,
        "regulatory": 0.172326,
        "other": 0.127283,
        **(FOUNDRY_ATTENTION.get("type_priors") or {}),
    }
    top_k = max(int(FOUNDRY_ATTENTION.get("top_k", 5)), 0)
    by_date = defaultdict(list)
    for row in decisions:
        event_type = _foundry_type_group(row.get("event_type"))
        row["attention_type_group"] = event_type
        row["attention_type_prior"] = float(priors.get(event_type, priors["other"]))
        by_date[row["date"]].append(row)
    for day_rows in by_date.values():
        day_rows.sort(key=lambda row: (
            -row["attention_type_prior"],
            -float(row.get("signal_score") or 0.0),
            row["ticker"],
        ))
        for rank, row in enumerate(day_rows, start=1):
            row["attention_rank"] = rank
            row["attention_candidate"] = bool(top_k and rank <= top_k)
            row["attention_status"] = (
                "attention_candidate" if row["attention_candidate"] else ""
            )
    return decisions


class FoundryData:
    """Read Signal-Foundry events as dashboard decision rows.

    Foundry emits event signals, not full daily score universes. For dashboard
    compatibility, each event/ticker pair becomes one decision row while the
    original event fields remain attached for the detail drawer and score view.
    Events are bucketed by the trading day they are actionable for (see
    `_trading_date`), so rows line up with the daily producers' dates and the
    price series; the raw publish timestamp stays on the row.
    """

    def __init__(self):
        self.name = "foundry"
        self.db = FOUNDRY_DB
        self.spec = {
            "metric": "signal_score",
            "history_metric": "signal_score",
            "history_extra": (
                "event_type",
                "sentiment",
                "source",
                "attention_type_prior",
                "attention_rank",
                "attention_candidate",
            ),
            "price_col": None,
            "hist_range": (0.0, 1.0),
            "hist_bins": 20,
        }
        self.fingerprint = None
        self.calendar = ()
        self.decisions = []
        self.scores = {}
        self.status = {}
        self.dates = []
        self.history = {}
        self.metric_values = []
        self.pipeline = {}
        self.n_signal_events = 0

    def stale(self, calendar=()):
        # Future-dated events re-snap when new trading days appear, so a
        # calendar change is as much a reload trigger as a DB write.
        return (_file_fingerprint(self.db) != self.fingerprint
                or tuple(calendar) != self.calendar)

    def load(self, calendar=()):
        fingerprint = _file_fingerprint(self.db)
        con = None
        if self.db.exists() and duckdb is not None:
            try:
                con = duckdb.connect(str(self.db), read_only=True)
            except duckdb.IOException:
                # Foundry's fetch/extract cycle holds the DuckDB write lock for
                # a few minutes; DuckDB then refuses even read-only attaches.
                # Keep serving the previously loaded events (fingerprint stays
                # unchanged, so the next request retries) instead of failing
                # every API call until the cycle finishes. Report "not loaded"
                # so callers don't treat a skipped attempt as a data change.
                return False

        self.fingerprint = fingerprint
        self.calendar = tuple(calendar)
        self.decisions = []
        self.scores = {}
        self.status = {}
        self.dates = []
        self.history = {}
        self.metric_values = []
        self.pipeline = {}
        self.n_signal_events = 0

        if con is None:
            return True

        where = ["e.is_signal", "e.tickers <> '[]'"]
        params = []
        if FOUNDRY_MODEL:
            where.append("e.model = ?")
            params.append(FOUNDRY_MODEL)
        if FOUNDRY_PROMPT:
            where.append("e.prompt_version = ?")
            params.append(FOUNDRY_PROMPT)
        try:
            rows = con.execute(
                f"""
                SELECT
                    e.item_id, e.model, e.prompt_version, e.extracted_at,
                    e.tickers, e.unknown_tickers, e.in_universe,
                    e.company_mentions, e.event_type, e.sentiment,
                    e.confidence, e.novelty, e.time_sensitivity,
                    e.evidence_quote, e.why_it_matters, e.source_quality,
                    e.signal_score, r.source, r.title, r.url, r.published_at
                FROM events e
                JOIN raw_items r ON r.id = e.item_id
                WHERE {" AND ".join(where)}
                ORDER BY r.published_at DESC, e.extracted_at DESC
                """,
                params,
            ).fetchall()
            self.pipeline = self._load_pipeline(con)
        finally:
            con.close()

        score_rows = defaultdict(list)
        groups = defaultdict(list)  # (trading day, ticker) -> contributing events
        for row in rows:
            (
                item_id, model, prompt, extracted_at, tickers_raw,
                unknown_raw, in_universe, mentions_raw, event_type, sentiment,
                confidence, novelty, time_sensitivity, evidence_quote,
                why_it_matters, source_quality, signal_score, source, title,
                url, published_at,
            ) = row
            tickers = [str(t).upper() for t in _json_list(tickers_raw) if str(t).strip()]
            if not tickers:
                continue

            event_date, _published_signal_date = _event_dates(published_at, self.calendar)
            _extracted_event_date, signal_date = _event_dates(extracted_at, self.calendar)
            if not event_date:
                event_date = _extracted_event_date
            if not signal_date:
                continue
            created_at = _iso_ts(extracted_at)
            raw_pub = "" if published_at is None else str(published_at).strip()
            # Date-only publish values (EDGAR backfill) stay date-only rather
            # than masquerading as a midnight-UTC timestamp.
            published_iso = raw_pub if len(raw_pub) == 10 else _iso_ts(published_at)
            unknown = {str(t).upper() for t in _json_list(unknown_raw)}
            mentions = [str(x) for x in _json_list(mentions_raw)]
            score = float(signal_score) if signal_score is not None else None

            for ticker in tickers:
                groups[(signal_date, ticker)].append({
                    "item_id": item_id, "model": model, "prompt_version": prompt,
                    "source": source, "title": title, "url": url,
                    "published_at": published_iso, "event_date": event_date,
                    "extracted_at": created_at, "event_type": event_type,
                    "sentiment": sentiment, "confidence": confidence,
                    "novelty": novelty, "time_sensitivity": time_sensitivity,
                    "evidence_quote": evidence_quote,
                    "why_it_matters": why_it_matters,
                    "source_quality": source_quality, "signal_score": score,
                    "unknown": ticker in unknown,
                    "in_universe": in_universe,
                    "company_mentions": mentions,
                })
                # The per-date "score file" stays event-level: it's the raw
                # browsable record, one row per event/ticker.
                score_rows[signal_date].append({
                    "ticker": ticker,
                    "signal_score": score,
                    "event_type": event_type,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "novelty": novelty,
                    "time_sensitivity": time_sensitivity,
                    "source": source,
                    "title": title,
                    "published_at": published_iso,
                    "extracted_at": created_at,
                    "item_id": item_id,
                })
                if isinstance(score, float) and math.isfinite(score):
                    self.metric_values.append(score)

        # One decision per ticker per trading day — the events are evidence,
        # the roll-up is the signal. The gate decides BUY/SELL/WATCH.
        for (signal_date, ticker), evs in groups.items():
            evs.sort(key=lambda e: e["published_at"] or "")
            unknown_ticker = any(e["unknown"] for e in evs)
            decision, reason, w_pos, w_neg = _foundry_gate(evs, unknown_ticker)
            top = max(evs, key=lambda e: (e["signal_score"] or 0.0,
                                          e["published_at"] or ""))
            first, last = evs[0], evs[-1]
            available_at = max((e["extracted_at"] or "" for e in evs)) or None
            self.decisions.append({
                "id": f"foundry:{signal_date}:{ticker}",
                "producer": self.name,
                "date": signal_date,
                "event_date": first["event_date"],
                "ticker": ticker,
                "decision": decision,
                "gate_reason": reason,
                "w_pos": round(w_pos, 3),
                "w_neg": round(w_neg, 3),
                "n_events": len({e["item_id"] for e in evs}),
                "sources": sorted({e["source"] for e in evs}),
                "metric": top["signal_score"],
                "signal_score": top["signal_score"],
                "created_at": available_at,
                "published_at": first["published_at"],
                "last_published_at": last["published_at"],
                "as_of_timestamp": available_at,
                "as_of_source": "foundry_extraction",
                "item_id": top["item_id"],
                "model": top["model"],
                "prompt_version": top["prompt_version"],
                "source": top["source"],
                "source_url": top["url"],
                "title": top["title"],
                "event_type": top["event_type"],
                "sentiment": top["sentiment"],
                "confidence": top["confidence"],
                "novelty": top["novelty"],
                "time_sensitivity": top["time_sensitivity"],
                "horizon": top["time_sensitivity"],
                "evidence_quote": top["evidence_quote"],
                "why_it_matters": top["why_it_matters"],
                "source_quality": top["source_quality"],
                "unknown_ticker": unknown_ticker,
                "in_universe": any(e["in_universe"] for e in evs),
                "extracted_at": top["extracted_at"],
                "events": [{k: e[k] for k in (
                    "source", "title", "url", "published_at", "sentiment",
                    "confidence", "signal_score", "event_type", "item_id")}
                    for e in evs],
            })
        _assign_foundry_attention(self.decisions)
        decision_lookup = {(row["date"], row["ticker"]): row for row in self.decisions}
        for signal_date, rows_for_date in score_rows.items():
            for score_row in rows_for_date:
                ranked = decision_lookup.get((signal_date, score_row["ticker"]), {})
                for field in (
                    "attention_type_group",
                    "attention_type_prior",
                    "attention_rank",
                    "attention_candidate",
                    "attention_status",
                ):
                    score_row[field] = ranked.get(field)
        for row in self.decisions:
            self.history.setdefault(row["ticker"], []).append({
                "date": row["date"],
                "metric": row["signal_score"],
                "px": None,
                "event_type": row["event_type"],
                "sentiment": row["sentiment"],
                "source": row["source"],
                "attention_type_prior": row["attention_type_prior"],
                "attention_rank": row["attention_rank"],
                "attention_candidate": row["attention_candidate"],
            })

        self.n_signal_events = len(
            {e["item_id"] for evs in groups.values() for e in evs})
        self.decisions.sort(key=lambda r: (
            sort_key(r["date"]), sort_key(r["ticker"]), sort_key(r["created_at"])))
        self.dates = sorted(score_rows)
        self.scores = {dt: pd.DataFrame(rows) for dt, rows in score_rows.items()}

        by_date = defaultdict(list)
        for r in self.decisions:
            by_date[r["date"]].append(r)
        for dt, rows_for_dt in score_rows.items():
            decs = by_date.get(dt, [])
            self.status[dt] = {
                "status": "ok",
                "events": len({r["item_id"] for r in rows_for_dt}),
                "tickers": len(decs),
                "buy": sum(1 for r in decs if r["decision"] == "BUY"),
                "sell": sum(1 for r in decs if r["decision"] == "SELL"),
                "watch": sum(1 for r in decs if r["decision"] == "WATCH"),
                "attention": sum(1 for r in decs if r.get("attention_candidate")),
            }

        for rows_for_ticker in self.history.values():
            rows_for_ticker.sort(key=lambda r: r["date"])
        return True

    def _load_pipeline(self, con):
        """Fetch/extract loop health, read from the same DB the events come from.

        Foundry has no premarket_status file; freshness per source is the
        run-health signal for an event producer (a source that stops producing
        looks exactly like a quiet news day otherwise).
        """
        pipe = {"sources": []}
        try:
            # epoch_ms because handing TIMESTAMPTZ values to Python needs pytz,
            # which this venv doesn't ship.
            for src, n, pub_ms, last_fetch in con.execute(
                """
                SELECT source, count(*),
                       epoch_ms(max(TRY_CAST(published_at AS TIMESTAMPTZ))),
                       max(fetched_at)
                FROM raw_items GROUP BY source ORDER BY source
                """
            ).fetchall():
                pipe["sources"].append({
                    "source": src,
                    "items": n,
                    "last_published": _iso_ts(
                        datetime.fromtimestamp(pub_ms / 1000, tz=timezone.utc)
                    ) if pub_ms is not None else None,
                    "last_fetched": _iso_ts(last_fetch),
                })
            pipe["last_fetch"] = _iso_ts(con.execute(
                "SELECT max(fetched_at) FROM raw_items").fetchone()[0])
            last_ext, n_events = con.execute(
                "SELECT max(extracted_at), count(*) FROM events"
                " WHERE model = ? AND prompt_version = ?",
                [FOUNDRY_MODEL, FOUNDRY_PROMPT],
            ).fetchone()
            pipe["last_extracted"] = _iso_ts(last_ext)
            pipe["events_extracted"] = n_events
            # Same pending semantics as foundry's own queue: no event yet for
            # the pinned model+prompt and not benched by repeated failures.
            pipe["pending"], pipe["benched"] = con.execute(
                """
                WITH benched AS (
                    SELECT item_id FROM failures
                    WHERE model = ? AND prompt_version = ?
                      AND error NOT LIKE '%429%' AND error NOT LIKE 'rate limited%'
                    GROUP BY item_id HAVING count(*) >= 3
                )
                SELECT
                    count(*) FILTER (WHERE e.item_id IS NULL
                                     AND r.id NOT IN (SELECT item_id FROM benched)),
                    (SELECT count(*) FROM benched)
                FROM raw_items r
                LEFT JOIN events e ON e.item_id = r.id
                     AND e.model = ? AND e.prompt_version = ?
                """,
                [FOUNDRY_MODEL, FOUNDRY_PROMPT, FOUNDRY_MODEL, FOUNDRY_PROMPT],
            ).fetchone()
        except Exception:
            # Never let health introspection break signal loading.
            pass
        return pipe

    def run_rows(self):
        by_date = defaultdict(list)
        for r in self.decisions:
            by_date[r["date"]].append(r)

        rows = []
        for dt in sorted(set(self.dates) | set(by_date)):
            decs = by_date.get(dt, [])
            st = self.status.get(dt, {})
            generated = max((r.get("created_at") for r in decs if r.get("created_at")),
                            default=None)
            rows.append({
                "producer": self.name,
                "date": dt,
                "status": st.get("status", "ok") if decs else None,
                "n_scores": len(self.scores[dt]) if dt in self.scores else 0,
                "n_events": st.get("events", 0),
                "n_decisions": len(decs),
                "n_buy": sum(1 for r in decs if r["decision"] == "BUY"),
                "n_attention": sum(1 for r in decs if r.get("attention_candidate")),
                "decision_summary": (
                    f"{sum(1 for r in decs if r['decision'] == 'SELL')} sell / "
                    f"{sum(1 for r in decs if r['decision'] == 'WATCH')} watch"
                ) if decs else None,
                "stale": None,
                "generated_at": generated,
                "as_of_date": None,
                "has_scores": dt in self.scores,
                "has_status": dt in self.status,
            })
        return rows


class Store:
    def __init__(self, gateway_factory=None):
        # Foundry is the only producer left: TB-92 removed LSTM and TB-93
        # then Intrinsic, and with them the file-based ProducerData class. The map
        # stays a mapping so every aggregation over `self.producers` still reads
        # the same, and so a second producer can be added back without reshaping
        # the store.
        self.producers = {"foundry": FoundryData()}
        self.price_book = ContinuousPriceBook()
        self.prices = {}         # compatibility index; values come only from gateway
        self.price_max_date = None  # latest traded session anywhere in the book
        self._price_src_fp = None
        self.gateway_factory = gateway_factory
        self.price_load_error = None
        self._refresh_lock = threading.Lock()
        self._snapshot_ready = False
        self._next_price_attempt = 0.0
        self._price_inputs_built = None
        self._price_thread = None
        # Bumped whenever the book is swapped. Anything expensive derived from
        # prices caches against this plus the producer's own fingerprint,
        # instead of recomputing per request.
        self.price_generation = 0

    def refresh(self):
        # Single-flight: a cold price build fires one continuous-ohlcv/bulk
        # call that the gateway computes per ticker. Letting every request
        # stack its own refresh starves the gateway until no call can finish,
        # so latecomers serve the current snapshot instead of piling on.
        if not self._refresh_lock.acquire(blocking=False):
            # On a cold start there is no prior snapshot to serve. Concurrent
            # first requests wait for the one loader instead of receiving an
            # authoritative-looking empty dashboard.
            if not self._snapshot_ready:
                self._refresh_lock.acquire()
                self._refresh_lock.release()
            return
        try:
            self._refresh_locked()
            self._snapshot_ready = True
        finally:
            self._refresh_lock.release()

    def _refresh_locked(self):
        changed = False
        # Foundry used to load last, snapping its events onto the trading
        # calendar the daily producers had just established. It is now the only
        # producer, so it is its own calendar source: the first load derives the
        # dates from its own events, and subsequent loads snap to those.
        cal = self.trading_calendar()
        foundry = self.producers["foundry"]
        if foundry.stale(cal) and foundry.load(cal):
            changed = True
        now = time.monotonic()
        if changed or not self.prices or now >= self._next_price_attempt:
            # The gateway price build takes minutes for a cold book, so it
            # runs in a background thread — API requests always serve the
            # current snapshot (signals visible, returns pending) instead of
            # blocking. Producer reloads only force a rebuild when they change
            # the price universe (tickers/start date): foundry event refreshes
            # land every cycle without moving the universe, and rebuilding the
            # whole book each time is ~20 gateway bulk calls of self-made load.
            # Same-universe refreshes wait out the TTL in _next_price_attempt,
            # which also refreshes the book when producers are quiet so new
            # gateway bars still land.
            if (
                (self._price_inputs() != self._price_inputs_built
                 or now >= self._next_price_attempt)
                and not self._price_build_busy()
            ):
                thread = threading.Thread(
                    target=self._price_build_worker,
                    daemon=True,
                    name="dashboard-price-build",
                )
                self._price_thread = thread
                thread.start()
            self._build_ticker_index()

    def _price_build_busy(self):
        thread = self._price_thread
        return thread is not None and thread.is_alive()

    def _price_inputs(self):
        """The decision universe the price book is built from."""
        tickers = frozenset(
            row["ticker"] for row in self.all_decisions if row.get("ticker")
        )
        dates = [row["date"] for row in self.all_decisions if row.get("date")]
        return (tickers, min(dates) if dates else None)

    def _price_build_worker(self):
        inputs = self._price_inputs()
        try:
            self._build_prices(inputs)
        finally:
            # Record the attempted inputs even on failure — retries are paced
            # by the TTL below, not by input mismatch, so one bad build can't
            # refire on every request.
            self._price_inputs_built = inputs
            self._next_price_attempt = time.monotonic() + (
                min(300.0, float(PRICE_REFRESH_SECONDS))
                if self.price_load_error
                else float(PRICE_REFRESH_SECONDS)
            )
            self._build_ticker_index()

    def trading_calendar(self):
        """Sorted trading dates every loaded producer has published.

        This iterated the file-based `PRODUCERS` registry, which is now empty, so
        it returned no dates at all even though Foundry had dozens -- and Foundry
        snaps its events onto this calendar. Reading `self.producers` keeps it
        honest with one producer and with any number.
        """
        ds = set()
        for producer in self.producers.values():
            ds.update(producer.dates)
        return tuple(sorted(ds))

    def producer_status_exit(self, producer, ticker, after_date, status):
        """First date > `after_date` on which `ticker` carried `status` in
        `producer`'s score history. Read-only over already-loaded history --
        no file reads, no new I/O."""
        prod = self.producers.get(producer)
        if prod is None or after_date is None:
            return None
        for row in getattr(prod, "history", {}).get(str(ticker).upper(), []):
            date = row.get("date")
            if date is None or date <= after_date:
                continue
            if row.get("status") == status:
                return date
        return None

    def _build_ticker_index(self):
        idx = {}
        for rec in self.all_decisions:
            e = idx.setdefault(rec["ticker"], {"ticker": rec["ticker"], "n_signals": 0,
                                               "last_signal": None, "producers": set()})
            if rec.get("decision") == "BUY":
                e["n_signals"] += 1
                e["producers"].add(rec["producer"])
                if e["last_signal"] is None or rec["date"] > e["last_signal"]:
                    e["last_signal"] = rec["date"]
        for producer in self.producers.values():
            for ticker in getattr(producer, "history", {}):
                idx.setdefault(ticker, {
                    "ticker": ticker,
                    "n_signals": 0,
                    "last_signal": None,
                    "producers": set(),
                })["producers"].add(producer.name)
        for t in self.prices:
            idx.setdefault(t, {"ticker": t, "n_signals": 0, "last_signal": None,
                               "producers": set()})
        self.ticker_index = {t: {**e, "producers": sorted(e["producers"])}
                             for t, e in idx.items()}

    def search_tickers(self, q, limit=15):
        qu = (q or "").upper().strip()
        if not qu:
            return []
        hits = [e for t, e in self.ticker_index.items() if qu in t]
        hits.sort(key=lambda e: (0 if e["ticker"].startswith(qu) else 1,
                                 -e["n_signals"], e["ticker"]))
        return hits[:limit]

    def _build_prices(self, inputs=None):
        tickers, start = inputs if inputs is not None else self._price_inputs()
        gateway = None
        try:
            if self.gateway_factory is not None:
                gateway = self.gateway_factory()
            else:
                gateway = HTTPGateway(AV_GATEWAY_URL)
            # Build off to the side and only swap after every gateway chunk
            # succeeds. A transient refresh failure must not discard the last
            # confirmed snapshot that is already serving the dashboard.
            next_book = ContinuousPriceBook()
            next_book.load(gateway, tickers, start=start)
            self.price_book = next_book
            self.price_load_error = None
            self.price_generation += 1
        except Exception as exc:
            # Fail closed: an unavailable/malformed gateway never introduces
            # reconstructed or partially loaded returns. The last fully
            # confirmed snapshot remains safe to serve, if one exists.
            self.price_load_error = str(exc)
        finally:
            if gateway is not None and hasattr(gateway, "close"):
                gateway.close()
        self.prices = {
            ticker: (
                [row["date"] for row in rows],
                [row["px"] for row in rows],
            )
            for ticker, rows in self.price_book.points.items()
        }
        # Staleness reference: a ticker is only "frozen" if it stops before the
        # rest of the book, never because a signal targets a future session.
        self.price_max_date = max(
            (rows[-1]["date"] for rows in self.price_book.points.values()),
            default=None,
        )

    # ---- price helpers ----

    def price_on(self, ticker, date):
        s = self.prices.get(ticker)
        if not s:
            return None
        dates, px = s
        i = bisect_left(dates, date)
        if i < len(dates) and dates[i] == date:
            return px[i]
        return None

    def fwd_price(self, ticker, date, n):
        """Price n observed trading days after `date` (n=0 -> on date)."""
        s = self.prices.get(ticker)
        if not s:
            return None, None
        dates, px = s
        i = bisect_left(dates, date)
        if i >= len(dates) or dates[i] != date:
            return None, None
        j = i + n
        if j >= len(dates):
            return None, None
        return px[j], dates[j]

    def last_price(self, ticker, after=None):
        s = self.prices.get(ticker)
        if not s:
            return None, None
        dates, px = s
        return px[-1], dates[-1]

    def _book_for(self, ticker):
        """Every ticker reads the decision book.

        TB-92 removed the second, candidate-only tier: it existed solely for
        one producer's score candidates, which outnumbered the decision universe
        roughly forty to one. With that producer gone there is one book, and a
        coverage gap keeps reporting its fail-closed reason rather than silently
        sourcing a second opinion.
        """
        return self.price_book

    def series(self, ticker, start=None):
        return self._book_for(ticker).series(ticker, start=start)

    def performance(self, ticker, date, *, sessions=None, through_last=False,
                    entry_snap=None):
        return self._book_for(ticker).performance(
            ticker, date, sessions=sessions, through_last=through_last,
            entry_snap=entry_snap,
        )

    def simulate_exit(self, ticker, entry_date, *, stop=None, target=None,
                      max_sessions=20, side="long", entry_snap=None,
                      trailing=False):
        return self._book_for(ticker).simulate_exit(
            ticker, entry_date, stop=stop, target=target,
            max_sessions=max_sessions, side=side, entry_snap=entry_snap,
            trailing=trailing,
        )

    def intraday_series(self, ticker, *, timeframe, start, end=None):
        gateway = (
            self.gateway_factory()
            if self.gateway_factory is not None
            else HTTPGateway(AV_GATEWAY_URL)
        )
        try:
            method = getattr(gateway, "intraday_ohlcv", None)
            if method is None:
                raise RuntimeError("intraday_ohlcv is required")
            payload = method(
                ticker,
                start=start,
                end=end,
                timeframe=timeframe,
                feed="iex",
                policy="dashboard",
            )
            return payload if isinstance(payload, list) else []
        finally:
            if hasattr(gateway, "close"):
                gateway.close()

    # ---- convenience ----

    @property
    def all_decisions(self):
        out = []
        for p in self.producers.values():
            out.extend(p.decisions)
        out.sort(key=lambda r: (
            sort_key(r["date"]), sort_key(r["producer"]), sort_key(r["ticker"])))
        return out

    @property
    def all_dates(self):
        ds = set()
        for p in self.producers.values():
            ds.update(p.dates)
        return sorted(ds)


STORE = Store()
