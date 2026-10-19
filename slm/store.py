"""Your desk inputs (desk.json) and the last run (desk_last.json, which Taursa reads). Both stay off GitHub."""
import json
from pathlib import Path

from .engine import SLEEVES

ROOT = Path(__file__).resolve().parent.parent
INPUTS, LAST = ROOT / "desk.json", ROOT / "desk_last.json"


def defaults():
    return {"funds": {s: f for s, _, f, _ in SLEEVES}, "holdings": {s: 0 for s, *_ in SLEEVES}, "repo_rate": None, "last_review": None,
            "stock_capital": 0, "unallocated_cash": 0, "positions": []}


def load():
    try:
        return defaults() | json.loads(INPUTS.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return defaults()


def save(cfg):
    INPUTS.write_text(json.dumps(cfg, indent=1, default=str), encoding="utf-8")


def save_last(result):
    LAST.write_text(json.dumps(result, default=str, ensure_ascii=False), encoding="utf-8")


def last():
    try:
        return json.loads(LAST.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
