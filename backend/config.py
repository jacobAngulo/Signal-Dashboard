import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_cfg_path = ROOT / "config.json"
if not _cfg_path.exists():
    _cfg_path = ROOT / "config.example.json"

CFG = json.loads(_cfg_path.read_text())

LSTM_DIR = Path(CFG["lstm_signals_dir"])
INTRINSIC_DIR = Path(CFG["intrinsic_signals_dir"])
FOUNDRY_DB = Path(CFG.get(
    "foundry_db",
    "/srv/data/signal-foundry/db/foundry.duckdb",
))
FOUNDRY_MODEL = CFG.get("foundry_model", "gpt-oss:20b")
FOUNDRY_PROMPT = CFG.get("foundry_prompt", "v2")

# Gate for rolling a ticker-day's foundry events into one BUY/SELL decision.
# Weights are signal_score × |sentiment|, so source quality, LLM confidence,
# novelty and sentiment strength all count. Defaults calibrated on the v2
# event distribution (2026-07): a directional EDGAR filing (score .5–.7)
# clears score_floor alone; HN/stocktwits (≤.43/.25) need aligned
# corroboration to reach net_floor; mixed chatter fails dominance.
FOUNDRY_GATE = {
    "score_floor": 0.45,   # one primary-source event with this score triggers
    "net_floor": 0.50,     # or accumulated aligned weight reaches this
    "dominance": 0.67,     # majority side must carry ≥ this share of weight
    **CFG.get("foundry_gate", {}),
}
FOUNDRY_ATTENTION = {
    "top_k": 5,
    "type_priors": {
        "earnings": 0.356855,
        "mna": 0.193548,
        "regulatory": 0.172326,
        "other": 0.127283,
    },
    **CFG.get("foundry_attention", {}),
}
HOST = CFG.get("host", "127.0.0.1")
PORT = int(CFG.get("port", 8010))
AV_GATEWAY_URL = os.environ.get(
    "AV_GATEWAY_URL", CFG.get("av_gateway_url", "http://127.0.0.1:8765")
).rstrip("/")
PRICE_REFRESH_SECONDS = max(
    60,
    int(os.environ.get(
        "PRICE_REFRESH_SECONDS",
        CFG.get("price_refresh_seconds", 300),
    )),
)
