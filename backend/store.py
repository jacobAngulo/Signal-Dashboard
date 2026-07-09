"""Load and cache signal files from the LSTM, Intrinsic, and Foundry producers.

Reads are strictly read-only against the producer repos' data outputs.
Everything is cached in memory and reloaded when the source dirs change.
"""
from collections import defaultdict
import json
import math
import os
import re
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    import duckdb
except ImportError:  # pragma: no cover - exercised only in an incomplete env
    duckdb = None

from .config import (
    FOUNDRY_DB,
    FOUNDRY_MODEL,
    FOUNDRY_PROMPT,
    INTRINSIC_DIR,
    LSTM_DIR,
)

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

PRODUCERS = {
    "lstm": {
        "dir": LSTM_DIR,
        "decision_glob": "live_decision_*.csv",
        "scores_glob": "live_scores_*.csv",
        "status_glob": "premarket_status_*.json",
        "price_col": "close",
        "metric": "adj_prob",
        "hist_range": (0.0, 0.35),
        "hist_bins": 14,
        # per-ticker score history exposed on ticker pages
        "history_metric": "best_adj_prob",
        "history_extra": ("best_horizon", "status"),
    },
    "intrinsic": {
        "dir": INTRINSIC_DIR,
        "decision_glob": "intrinsic_decision_*.csv",
        "scores_glob": "intrinsic_scores_*.csv",
        "status_glob": "premarket_status_*.json",
        "price_col": "price",
        "metric": "discount_to_intrinsic",
        "hist_range": (0.0, 1.0),
        "hist_bins": 20,
        "history_metric": "discount_to_intrinsic",
        "history_extra": ("intrinsic_value", "status"),
    },
}


def file_date(path: Path):
    m = DATE_RE.search(path.name)
    return m.group(1) if m else None


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


def _read_csv(path: Path):
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    df.columns = [c.strip() for c in df.columns]
    return df


def _fingerprint(d: Path):
    try:
        return tuple(sorted((e.name, e.stat().st_mtime_ns, e.stat().st_size)
                            for e in os.scandir(d) if e.is_file()))
    except FileNotFoundError:
        return ()


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


def _date_from_ts(v):
    iso = _iso_ts(v)
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        m = DATE_RE.search(iso)
        return m.group(1) if m else None


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


def _foundry_decision(sentiment):
    try:
        s = int(sentiment)
    except (TypeError, ValueError):
        s = 0
    if s > 0:
        return "BUY"
    if s < 0:
        return "SELL"
    return "WATCH"


class ProducerData:
    def __init__(self, name: str):
        self.name = name
        self.spec = PRODUCERS[name]
        self.fingerprint = None
        self.decisions = []          # list[dict], normalized + raw fields
        self.scores = {}             # date -> DataFrame
        self.status = {}             # date -> raw status json (+ _mtime)
        self.dates = []              # sorted trading dates seen in scores
        self.history = {}            # ticker -> [{date, metric, px, ...}]
        self.metric_values = []      # metric across the whole score universe

    def stale(self):
        return _fingerprint(self.spec["dir"]) != self.fingerprint

    def load(self):
        d = self.spec["dir"]
        self.fingerprint = _fingerprint(d)
        self.scores = {}
        self.status = {}
        self.decisions = []

        for p in sorted(d.glob(self.spec["scores_glob"])):
            dt = file_date(p)
            if dt:
                self.scores[dt] = _read_csv(p)

        for p in sorted(d.glob(self.spec["status_glob"])):
            dt = file_date(p)
            if not dt:
                continue
            try:
                raw = json.loads(p.read_text())
            except Exception:
                raw = {"status": "unreadable"}
            raw["_mtime"] = p.stat().st_mtime
            self.status[dt] = raw

        for p in sorted(d.glob(self.spec["decision_glob"])):
            dt = file_date(p)
            df = _read_csv(p)
            # Decision CSVs only carry dates; the file mtime is the actual
            # creation time (matches LSTM's status finished_at to the second).
            created = datetime.fromtimestamp(
                p.stat().st_mtime, tz=timezone.utc).isoformat()
            for i, row in enumerate(df.to_dict("records")):
                rec = {k: v for k, v in row.items()}
                rec["producer"] = self.name
                rec["date"] = dt
                rec["ticker"] = str(row.get("ticker", "")).upper()
                rec["decision"] = str(row.get("decision", "")).upper() or None
                rec["metric"] = row.get(self.spec["metric"])
                rec["created_at"] = created
                rec["id"] = f"{self.name}:{dt}:{rec['ticker']}:{i}"
                self.decisions.append(rec)

        self.dates = sorted(self.scores.keys())
        self._build_history()

    def _build_history(self):
        """Per-ticker daily score history + full-universe metric sample."""
        metric_col = self.spec["history_metric"]
        px_col = self.spec["price_col"]
        extra = self.spec["history_extra"]
        self.history = {}
        self.metric_values = []
        for dt in self.dates:
            df = self.scores[dt]
            if "ticker" not in df.columns:
                continue
            cols = [c for c in (metric_col, px_col, *extra) if c in df.columns]
            for row in df[["ticker", *cols]].itertuples(index=False):
                rec = dict(zip(("ticker", *cols), row))
                t = str(rec.pop("ticker")).upper()
                h = {"date": dt, "metric": rec.get(metric_col), "px": rec.get(px_col)}
                for e in extra:
                    if e in rec:
                        h[e] = rec[e]
                self.history.setdefault(t, []).append(h)
                m = rec.get(metric_col)
                if isinstance(m, float) and math.isfinite(m):
                    self.metric_values.append(m)

    def run_rows(self):
        """One row per known date: run health + volumes."""
        dates = sorted(set(self.dates) | set(self.status) |
                       {r["date"] for r in self.decisions})
        by_date = {}
        for r in self.decisions:
            by_date.setdefault(r["date"], []).append(r)
        rows = []
        for dt in dates:
            st = self.status.get(dt, {})
            decs = by_date.get(dt, [])
            n_scores = len(self.scores[dt]) if dt in self.scores else None
            stale_rows = st.get("stale_rows") or {}
            rows.append({
                "producer": self.name,
                "date": dt,
                "status": st.get("status"),
                "n_scores": n_scores,
                "n_decisions": len(decs),
                "n_buy": sum(1 for r in decs if r["decision"] == "BUY"),
                "decision_summary": st.get("decision"),
                "stale": sum(stale_rows.values()) if stale_rows else None,
                "generated_at": st.get("finished_at") or st.get("generated_at")
                    or (datetime.fromtimestamp(st["_mtime"], tz=timezone.utc)
                        .isoformat() if "_mtime" in st else None),
                "as_of_date": st.get("as_of_date"),
                "has_scores": dt in self.scores,
                "has_status": dt in self.status,
            })
        return rows


class FoundryData:
    """Read Signal-Foundry events as dashboard decision rows.

    Foundry emits event signals, not full daily score universes. For dashboard
    compatibility, each event/ticker pair becomes one decision row while the
    original event fields remain attached for the detail drawer and score view.
    """

    def __init__(self):
        self.name = "foundry"
        self.db = FOUNDRY_DB
        self.spec = {
            "metric": "signal_score",
            "history_metric": "signal_score",
            "history_extra": ("event_type", "sentiment", "source"),
            "price_col": None,
            "hist_range": (0.0, 1.0),
            "hist_bins": 20,
        }
        self.fingerprint = None
        self.decisions = []
        self.scores = {}
        self.status = {}
        self.dates = []
        self.history = {}
        self.metric_values = []

    def stale(self):
        return _file_fingerprint(self.db) != self.fingerprint

    def load(self):
        self.fingerprint = _file_fingerprint(self.db)
        self.decisions = []
        self.scores = {}
        self.status = {}
        self.dates = []
        self.history = {}
        self.metric_values = []

        if not self.db.exists() or duckdb is None:
            return

        where = ["e.is_signal", "e.tickers <> '[]'"]
        params = []
        if FOUNDRY_MODEL:
            where.append("e.model = ?")
            params.append(FOUNDRY_MODEL)
        if FOUNDRY_PROMPT:
            where.append("e.prompt_version = ?")
            params.append(FOUNDRY_PROMPT)

        con = duckdb.connect(str(self.db), read_only=True)
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
        finally:
            con.close()

        score_rows = defaultdict(list)
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

            signal_date = _date_from_ts(published_at) or _date_from_ts(extracted_at)
            if not signal_date:
                continue
            created_at = _iso_ts(extracted_at)
            published_iso = _iso_ts(published_at)
            unknown = [str(t).upper() for t in _json_list(unknown_raw)]
            mentions = [str(x) for x in _json_list(mentions_raw)]
            decision = _foundry_decision(sentiment)
            score = float(signal_score) if signal_score is not None else None

            for i, ticker in enumerate(tickers):
                rec = {
                    "id": f"foundry:{item_id}:{ticker}:{i}",
                    "producer": self.name,
                    "date": signal_date,
                    "ticker": ticker,
                    "decision": decision,
                    "metric": score,
                    "signal_score": score,
                    "created_at": created_at,
                    "as_of_timestamp": published_iso,
                    "as_of_source": source,
                    "model": model,
                    "prompt_version": prompt,
                    "item_id": item_id,
                    "source": source,
                    "source_url": url,
                    "title": title,
                    "event_type": event_type,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "novelty": novelty,
                    "time_sensitivity": time_sensitivity,
                    "horizon": time_sensitivity,
                    "evidence_quote": evidence_quote,
                    "why_it_matters": why_it_matters,
                    "source_quality": source_quality,
                    "unknown_tickers": unknown,
                    "company_mentions": mentions,
                    "in_universe": in_universe,
                    "published_at": published_iso,
                    "extracted_at": created_at,
                }
                self.decisions.append(rec)
                score_rows[signal_date].append({
                    "ticker": ticker,
                    "decision": decision,
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
                self.history.setdefault(ticker, []).append({
                    "date": signal_date,
                    "metric": score,
                    "px": None,
                    "event_type": event_type,
                    "sentiment": sentiment,
                    "source": source,
                })
                if isinstance(score, float) and math.isfinite(score):
                    self.metric_values.append(score)

        self.decisions.sort(key=lambda r: (r["date"], r["ticker"], r["created_at"] or ""))
        self.dates = sorted(score_rows)
        self.scores = {dt: pd.DataFrame(rows) for dt, rows in score_rows.items()}

        for dt, rows_for_dt in score_rows.items():
            self.status[dt] = {
                "status": "ok",
                "events": len({r["item_id"] for r in rows_for_dt}),
                "ticker_rows": len(rows_for_dt),
                "buy": sum(1 for r in rows_for_dt if r["decision"] == "BUY"),
                "sell": sum(1 for r in rows_for_dt if r["decision"] == "SELL"),
                "watch": sum(1 for r in rows_for_dt if r["decision"] == "WATCH"),
            }

        for rows_for_ticker in self.history.values():
            rows_for_ticker.sort(key=lambda r: r["date"])

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
                "n_decisions": len(decs),
                "n_buy": sum(1 for r in decs if r["decision"] == "BUY"),
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
    def __init__(self):
        self.producers = {name: ProducerData(name) for name in PRODUCERS}
        self.producers["foundry"] = FoundryData()
        self.prices = {}         # ticker -> (dates[], px[])
        self._price_src_fp = None

    def refresh(self):
        changed = False
        for p in self.producers.values():
            if p.stale():
                p.load()
                changed = True
        if changed or not self.prices:
            self._build_prices()
            self._build_ticker_index()

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

    def _build_prices(self):
        # Daily per-ticker prices reconstructed from the producers' own score
        # files (LSTM `close` preferred, then intrinsic `price`), so the price
        # series is aligned with signal dates by construction.
        px = {}  # ticker -> {date: price}
        for name, col_pref in (("intrinsic", "price"), ("lstm", "close")):
            prod = self.producers[name]
            col = prod.spec["price_col"]
            for dt, df in prod.scores.items():
                if col not in df.columns or "ticker" not in df.columns:
                    continue
                sub = df[["ticker", col]].dropna()
                for t, v in zip(sub["ticker"].astype(str).str.upper(), sub[col]):
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(v) and v > 0:
                        px.setdefault(t, {})[dt] = v
        self.prices = {}
        for t, series in px.items():
            dates = sorted(series)
            self.prices[t] = (dates, [series[d] for d in dates])

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

    def series(self, ticker, start=None):
        s = self.prices.get(ticker)
        if not s:
            return []
        dates, px = s
        out = [{"date": d, "px": p} for d, p in zip(dates, px)]
        if start:
            out = [r for r in out if r["date"] >= start]
        return out

    # ---- convenience ----

    @property
    def all_decisions(self):
        out = []
        for p in self.producers.values():
            out.extend(p.decisions)
        out.sort(key=lambda r: (r["date"], r["producer"], r["ticker"]))
        return out

    @property
    def all_dates(self):
        ds = set()
        for p in self.producers.values():
            ds.update(p.dates)
        return sorted(ds)


STORE = Store()
