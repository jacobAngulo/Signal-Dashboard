"""Read-only view of Trading-Bot-Arena execution state.

Local arena.sqlite3 gives per-bot orders/positions (ownership splits).
The live arena API is used for Alpaca-authoritative market prices — per the
arena's own rule, locally derived P&L is indicative, Alpaca is the truth.
"""
import json
import sqlite3
import time
import urllib.request
from collections import defaultdict

from .config import ARENA_DB, ARENA_API


def _connect():
    return sqlite3.connect(f"file:{ARENA_DB}?mode=ro", uri=True)


class ArenaData:
    def __init__(self):
        self._mtime = None
        self.bots = {}            # bot_id -> {name, family, producers:set}
        self.orders = []          # dicts, filled + pending
        self.positions = []      # open per-bot rows from sqlite
        self._live = {"ts": 0.0, "prices": {}}

    # ---- loading ----

    def stale(self):
        try:
            return ARENA_DB.stat().st_mtime != self._mtime
        except FileNotFoundError:
            return False

    def refresh(self):
        if not ARENA_DB.exists() or not self.stale():
            return
        self._mtime = ARENA_DB.stat().st_mtime
        con = _connect()
        try:
            self.bots = {}
            for bid, name, cfg in con.execute("SELECT id, name, config_json FROM bots"):
                family = None
                try:
                    family = (json.loads(cfg) or {}).get("family")
                except Exception:
                    pass
                label = (name or "").lower()
                producers = set()
                if "lstm" in label or "mixed" in label:
                    producers.add("lstm")
                if "intrinsic" in label or "mixed" in label:
                    producers.add("intrinsic")
                self.bots[bid] = {"name": name, "family": family, "producers": producers}

            self.orders = []
            q = ("SELECT id, bot_id, order_id, symbol, side, qty, status, "
                 "timestamp, fill_price, fill_qty, reason FROM orders ORDER BY timestamp")
            for row in con.execute(q):
                (oid, bot_id, order_id, symbol, side, qty, status,
                 ts, fill_price, fill_qty, reason) = row
                bot = self.bots.get(bot_id, {})
                self.orders.append({
                    "id": oid, "bot_id": bot_id, "bot": bot.get("name"),
                    "producers": sorted(bot.get("producers", ())),
                    "symbol": (symbol or "").upper(), "side": side,
                    "qty": qty, "status": status, "timestamp": ts,
                    "date": (ts or "")[:10],
                    "fill_price": fill_price, "fill_qty": fill_qty,
                    "reason": reason,
                })

            self.positions = []
            for bot_id, symbol, qty, cost_basis in con.execute(
                    "SELECT bot_id, symbol, qty, cost_basis FROM positions"):
                bot = self.bots.get(bot_id, {})
                self.positions.append({
                    "bot": bot.get("name"), "bot_id": bot_id,
                    "producers": sorted(bot.get("producers", ())),
                    "symbol": (symbol or "").upper(),
                    "qty": qty, "cost_basis": cost_basis,
                })
        finally:
            con.close()
        self._index()

    def _index(self):
        self.buys_by_symbol_date = defaultdict(list)
        self.orders_by_symbol = defaultdict(list)
        for o in self.orders:
            self.orders_by_symbol[o["symbol"]].append(o)
            if o["side"] == "buy":
                self.buys_by_symbol_date[(o["symbol"], o["date"])].append(o)
        self._round_trips = None

    # ---- live prices (Alpaca truth via arena API) ----

    def live_prices(self):
        if time.time() - self._live["ts"] > 60:
            prices = {}
            try:
                with urllib.request.urlopen(f"{ARENA_API}/positions", timeout=4) as r:
                    for p in json.loads(r.read()):
                        if p.get("market_price"):
                            prices[p["symbol"].upper()] = float(p["market_price"])
                self._live = {"ts": time.time(), "prices": prices}
            except Exception:
                self._live["ts"] = time.time() - 45  # retry soon, keep old data
        return self._live["prices"]

    # ---- round trips (FIFO per bot+symbol over filled orders) ----

    def round_trips(self):
        if self._round_trips is not None:
            return self._round_trips
        lots = defaultdict(list)   # (bot_id, symbol) -> open lots
        trips = []
        for o in self.orders:
            if o["status"] != "filled" or not o["fill_qty"] or not o["fill_price"]:
                continue
            key = (o["bot_id"], o["symbol"])
            if o["side"] == "buy":
                lots[key].append({"qty": o["fill_qty"], "px": o["fill_price"],
                                  "date": o["date"], "bot": o["bot"],
                                  "producers": o["producers"]})
            else:
                remaining = o["fill_qty"]
                while remaining > 1e-9 and lots[key]:
                    lot = lots[key][0]
                    take = min(lot["qty"], remaining)
                    trips.append({
                        "bot": o["bot"], "symbol": o["symbol"],
                        "producers": lot["producers"],
                        "entry_date": lot["date"], "exit_date": o["date"],
                        "qty": take, "entry_px": lot["px"], "exit_px": o["fill_price"],
                        "pnl": take * (o["fill_price"] - lot["px"]),
                        "ret": (o["fill_price"] / lot["px"] - 1) if lot["px"] else None,
                    })
                    lot["qty"] -= take
                    remaining -= take
                    if lot["qty"] <= 1e-9:
                        lots[key].pop(0)
        self._open_lots = {k: v for k, v in lots.items() if v}
        self._round_trips = trips
        return trips

    def open_lots(self):
        self.round_trips()
        return self._open_lots

    # ---- signal enrichment ----

    def match_signal(self, producer, date, ticker):
        """Execution summary for a signal: buys that day by bots fed by this
        producer, later sells against those lots, and what remains open."""
        buys = [o for o in self.buys_by_symbol_date.get((ticker, date), [])
                if producer in o["producers"]]
        if not buys:
            return {"traded": False}
        bot_ids = {o["bot_id"] for o in buys}
        trips = [t for t in self.round_trips()
                 if t["symbol"] == ticker and t["entry_date"] == date
                 and producer in t["producers"]]
        open_qty = open_cost = 0.0
        for (bot_id, sym), lot_list in self.open_lots().items():
            if sym != ticker or bot_id not in bot_ids:
                continue
            for lot in lot_list:
                if lot["date"] == date:
                    open_qty += lot["qty"]
                    open_cost += lot["qty"] * lot["px"]
        filled = [o for o in buys if o["status"] == "filled" and o["fill_qty"]]
        tot_qty = sum(o["fill_qty"] for o in filled)
        avg_px = (sum(o["fill_qty"] * o["fill_price"] for o in filled) / tot_qty
                  if tot_qty else None)
        realized = sum(t["pnl"] for t in trips)
        if open_qty > 1e-9:
            state = "open" if not trips else "partial"
        elif trips:
            state = "closed"
        elif filled:
            state = "closed"   # filled but lots consumed elsewhere (defensive)
        else:
            state = "pending"
        live_px = self.live_prices().get(ticker)
        unrealized = (open_qty * live_px - open_cost) if (open_qty and live_px) else None
        return {
            "traded": True,
            "state": state,
            "bots": sorted({o["bot"] for o in buys}),
            "n_bots": len({o["bot"] for o in buys}),
            "fill_qty": tot_qty or None,
            "avg_fill_px": avg_px,
            "realized_pnl": realized if trips else None,
            "open_qty": open_qty or None,
            "open_cost": open_cost or None,
            "unrealized_pnl": unrealized,
            "exits": [{"date": t["exit_date"], "px": t["exit_px"], "qty": t["qty"],
                       "pnl": t["pnl"], "bot": t["bot"]} for t in trips],
        }


ARENA = ArenaData()
