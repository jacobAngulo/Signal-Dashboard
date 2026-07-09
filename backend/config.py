import json
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
    "/root/.openclaw/workspace/Signal-Foundry/data/foundry.duckdb",
))
FOUNDRY_MODEL = CFG.get("foundry_model", "gpt-oss:20b")
FOUNDRY_PROMPT = CFG.get("foundry_prompt", "v2")
HOST = CFG.get("host", "127.0.0.1")
PORT = int(CFG.get("port", 8010))
