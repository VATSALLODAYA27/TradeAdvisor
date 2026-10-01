"""Daily history database (SQLite, part of Python): one snapshot of metrics per symbol per day.

Filled every time you analyze a symbol and every time the morning brief runs, so trends (PCR, IV, signal score)
and IV rank build up over time. Stored in history.db next to the app.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

FILE = Path(__file__).with_name("history.db")
KEEP = ("price", "close", "atm_iv", "pcr_oi", "max_pain", "call_wall", "put_wall", "vix", "nifty", "rsi", "sig_score",
        "mtf_score", "vs_bias", "fii_net_cr", "dii_net_cr", "vol_ratio", "days_to_expiry")


def _db():
    con = sqlite3.connect(FILE)
    con.execute("CREATE TABLE IF NOT EXISTS snap (day TEXT, symbol TEXT, data TEXT, PRIMARY KEY (day, symbol))")
    return con


def record(symbol, metrics, verdicts=None, day=None):
    """Save today's snapshot (a later analysis on the same day replaces it)."""
    row = {k: metrics[k] for k in KEEP if isinstance(metrics.get(k), (int, float))}
    row["verdicts"] = {n: v["verdict"] for n, v in (verdicts or {}).items()}
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO snap VALUES (?, ?, ?)", ((day or date.today()).isoformat(), symbol, json.dumps(row)))


def series(symbol):
    """All snapshots for a symbol as a DataFrame indexed by date."""
    with _db() as con:
        rows = con.execute("SELECT day, data FROM snap WHERE symbol = ? ORDER BY day", (symbol,)).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([json.loads(d) for _, d in rows], index=pd.to_datetime([d for d, _ in rows]))


def iv_rank(symbol, current_iv, min_days=5):
    """Where today's ATM IV sits between the lowest (0) and highest (100) IV we have stored. None until min_days of data."""
    df = series(symbol)
    if "atm_iv" not in df or df["atm_iv"].count() < min_days or current_iv is None:
        return None
    lo, hi = df["atm_iv"].min(), df["atm_iv"].max()
    return round((current_iv - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0


def symbols():
    with _db() as con:
        return [r[0] for r in con.execute("SELECT symbol, COUNT(*) n FROM snap GROUP BY symbol ORDER BY n DESC")]


if __name__ == "__main__":
    import tempfile
    FILE = Path(tempfile.mkdtemp()) / "t.db"
    for i, iv in enumerate([10, 20, 15, 12, 18]):
        record("X", {"atm_iv": iv, "pcr_oi": 1.0 + i / 10, "sector": "text is ignored"}, {"swing": {"verdict": "BUY"}},
               day=date(2026, 9, 20 + i))
    record("X", {"atm_iv": 19}, day=date(2026, 9, 24))  # same day replaces
    s = series("X")
    assert len(s) == 5 and s["atm_iv"].iloc[-1] == 19 and "sector" not in s
    assert iv_rank("X", 15) == 50.0 and iv_rank("X", 20) == 100.0 and iv_rank("Y", 15) is None
    print("ok")
