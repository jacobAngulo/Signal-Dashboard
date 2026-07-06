import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_cfg_path = ROOT / "config.json"
if not _cfg_path.exists():
    _cfg_path = ROOT / "config.example.json"

CFG = json.loads(_cfg_path.read_text())

LSTM_DIR = Path(CFG["lstm_signals_dir"])
INTRINSIC_DIR = Path(CFG["intrinsic_signals_dir"])
HOST = CFG.get("host", "127.0.0.1")
PORT = int(CFG.get("port", 8010))
