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

# Google OAuth client credentials, consumed by the sign-in flow in `auth.py`.
# Environment only, with no config.json fallback: the app reads config.json at
# mode 0644, and a client secret must never live there. Ops Console -> Google
# Cloud owns the values and restarts the unit to load them.
GOOGLE_CLIENT_ID = os.environ.get("AUTH_GOOGLE_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("AUTH_GOOGLE_SECRET", "").strip()

# The entire authorization policy. A verified Google identity that is not on
# this list gets nothing -- there is no self-service, no request queue, and no
# implicit owner. Same environment-only reasoning as the secret above: this is
# a list of real people's addresses and config.json is world-readable.
#
# As of the access-request cutover this is kept only for the fail-closed boot
# check in AUTH_CONFIGURED below -- the actual gate is the access_request
# table in the auth DB. An empty list still means "nobody" at startup, but
# once the process is up the table is the source of truth.
AUTH_ALLOWED_EMAILS = frozenset(
    part.strip().lower()
    for part in os.environ.get("AUTH_ALLOWED_EMAILS", "").split(",")
    if part.strip()
)

# Matches the console's OPS_GOOGLE_SESSION_TTL_S default. The floor exists so a
# typo cannot produce a session that expires faster than a page can load.
AUTH_SESSION_TTL_S = max(300, int(os.environ.get("AUTH_SESSION_TTL_S", "1800")))

# Outside the repo, like every other piece of state on this box. Disposable:
# deleting it signs everyone out and costs nothing else, which is why it is
# declared with backups off.
AUTH_DB_PATH = Path(
    os.environ.get("AUTH_DB_PATH", "/srv/data/signal-dashboard/db/auth.sqlite3")
)

# Bearer token for the loopback-only /api/admin surface the ops console calls
# to approve or deny access requests. An unset or short value disables the
# surface entirely (fail-closed), matching the industry-ops pattern.
ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")

# True once this process can actually run a sign-in. When it is False the gate
# refuses everyone rather than admitting everyone -- see `auth.configured`.
AUTH_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Project-scoped Ticket Board intake stays server-side. Browser feedback is
# posted to this app's own /api/feedback route.
TICKET_BOARD_URL = os.environ.get("TICKET_BOARD_URL", "http://127.0.0.1:8040").rstrip("/")
TICKET_BOARD_PROJECT_SLUG = os.environ.get("TICKET_BOARD_PROJECT_SLUG", "signal-dashboard")
TICKET_BOARD_INTAKE_TOKEN = os.environ.get("TICKET_BOARD_INTAKE_TOKEN", "")
