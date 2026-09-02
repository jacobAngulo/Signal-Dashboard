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
# The candidate price book is a second tier behind the decision book: ~2.7k
# LSTM score candidates against the decision universe's ~70 tickers, which is
# roughly 29 gateway bulk chunks and about five minutes per rebuild. Refreshing
# that on the decision cadence would leave the builder running permanently, so
# candidate returns are deliberately allowed to lag. Decision returns keep the
# fast tier and are unaffected.
CANDIDATE_PRICE_REFRESH_SECONDS = max(
    300,
    int(os.environ.get(
        "CANDIDATE_PRICE_REFRESH_SECONDS",
        CFG.get("candidate_price_refresh_seconds", 1800),
    )),
)

# Google OAuth client credentials, consumed by the sign-in flow in `auth.py`.
# Environment only, with no config.json fallback: the app reads config.json at
# mode 0644, and a client secret must never live there. Ops Console -> Google
# Cloud owns the values and restarts the unit to load them.
GOOGLE_CLIENT_ID = os.environ.get("AUTH_GOOGLE_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("AUTH_GOOGLE_SECRET", "").strip()

# Retained for backwards-compatible deployment configuration only. The
# access-request table is now the authorization policy for Google and password
# accounts alike, so this value is not consulted by the request gate.
AUTH_ALLOWED_EMAILS = frozenset(
    part.strip().lower()
    for part in os.environ.get("AUTH_ALLOWED_EMAILS", "").split(",")
    if part.strip()
)

# Sessions are renewed while the browser is active, so an ordinary return visit
# does not require another sign-in.  A fixed absolute ceiling limits a cookie
# that is stolen and never explicitly revoked.
AUTH_SESSION_TTL_S = max(300, int(os.environ.get("AUTH_SESSION_TTL_S", str(30 * 24 * 60 * 60))))
AUTH_SESSION_ABSOLUTE_TTL_S = max(
    AUTH_SESSION_TTL_S,
    int(os.environ.get("AUTH_SESSION_ABSOLUTE_TTL_S", str(90 * 24 * 60 * 60))),
)

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

# True when the optional Google provider can complete a sign-in. Password
# sign-in remains available when this is false.
AUTH_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Project-scoped Ticket Board intake stays server-side. Browser feedback is
# posted to this app's own /api/feedback route.
TICKET_BOARD_URL = os.environ.get("TICKET_BOARD_URL", "http://127.0.0.1:8040").rstrip("/")
TICKET_BOARD_PROJECT_SLUG = os.environ.get("TICKET_BOARD_PROJECT_SLUG", "signal-dashboard")
TICKET_BOARD_INTAKE_TOKEN = os.environ.get("TICKET_BOARD_INTAKE_TOKEN", "")
