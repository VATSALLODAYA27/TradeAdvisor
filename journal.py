"""Trade journal: your trades in trades.csv (open in Excel any time), plus the dashboard statistics."""
from datetime import date
from pathlib import Path

import pandas as pd

FILE = Path(__file__).with_name("trades.csv")
COLUMNS = ["date", "symbol", "instrument", "side", "qty", "entry", "stop", "target", "exit", "exit_date", "status", "setup", "notes"]
NUMERIC = ["qty", "entry", "stop", "target", "exit"]


def load():
    df = pd.read_csv(FILE) if FILE.exists() else pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df:
            df[c] = None
    df = df[COLUMNS]
    df[NUMERIC] = df[NUMERIC].apply(pd.to_numeric, errors="coerce")
    for c in ("date", "exit_date"):  # plain date objects (an all-empty column would otherwise become datetime64)
        df[c] = pd.Series([x.date() if pd.notna(x) else None for x in pd.to_datetime(df[c], errors="coerce")],
                          index=df.index, dtype="object")
    for c in ("symbol", "instrument", "side", "status", "setup", "notes"):
        df[c] = df[c].astype("string")
    return df


def save(df):
    df = df.copy()
    df["status"] = df.apply(lambda r: "CLOSED" if pd.notna(r["exit"]) else (r["status"] if pd.notna(r["status"]) else "OPEN"), axis=1)
    df[COLUMNS].to_csv(FILE, index=False)


def add(symbol, side, qty, entry, stop=None, target=None, instrument="Stock", setup="", notes=""):
    df = load()
    row = {"date": date.today(), "symbol": symbol, "instrument": instrument, "side": side, "qty": qty, "entry": entry,
           "stop": stop, "target": target, "exit": None, "exit_date": None, "status": "OPEN", "setup": setup, "notes": notes}
    save(pd.concat([df, pd.DataFrame([row])], ignore_index=True))


def with_pnl(df):
    """Adds pnl (₹), r_multiple (pnl / planned risk) and win for closed trades."""
    df = df.copy()
    sgn = df["side"].str.upper().map({"BUY": 1, "SELL": -1}).fillna(1)
    df["pnl"] = (df["exit"] - df["entry"]) * df["qty"] * sgn
    risk = (df["entry"] - df["stop"]).abs() * df["qty"]
    df["r_multiple"] = df["pnl"] / risk.where(risk > 0)
    df["win"] = df["pnl"] > 0
    return df


def stats(df):
    closed = with_pnl(df)[lambda x: x["exit"].notna()]
    if closed.empty:
        return {"trades": 0, "open": int((df["status"] == "OPEN").sum())}
    wins, losses = closed[closed["pnl"] > 0]["pnl"], closed[closed["pnl"] <= 0]["pnl"]
    curve = closed.sort_values(["exit_date", "date"])[["exit_date", "pnl"]].assign(equity=lambda x: x["pnl"].cumsum())
    peak = curve["equity"].cummax()
    return {
        "trades": len(closed), "open": int((df["status"] == "OPEN").sum()),
        "total_pnl": float(closed["pnl"].sum()), "win_rate": float(len(wins) / len(closed) * 100),
        "avg_win": float(wins.mean()) if len(wins) else 0.0, "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        "expectancy": float(closed["pnl"].mean()), "avg_r": float(closed["r_multiple"].mean()) if closed["r_multiple"].notna().any() else None,
        "max_drawdown": float((curve["equity"] - peak).min()), "curve": curve,
        "by_symbol": closed.groupby("symbol")["pnl"].sum().sort_values(),
        "by_setup": closed.groupby(closed["setup"].fillna("—"))["pnl"].agg(["count", "sum"]),
    }


if __name__ == "__main__":
    t = pd.DataFrame([
        {"date": date(2026, 9, 1), "symbol": "A", "side": "BUY", "qty": 10, "entry": 100, "stop": 95, "exit": 110, "exit_date": date(2026, 9, 2)},
        {"date": date(2026, 9, 3), "symbol": "B", "side": "SELL", "qty": 5, "entry": 200, "stop": 210, "exit": 220, "exit_date": date(2026, 9, 4)},
        {"date": date(2026, 9, 5), "symbol": "C", "side": "BUY", "qty": 1, "entry": 50, "stop": 45, "status": "OPEN"},
    ]).reindex(columns=COLUMNS)
    s = stats(t)
    assert s["trades"] == 2 and s["open"] == 1 and s["total_pnl"] == 100 - 100 and s["win_rate"] == 50
    assert s["profit_factor"] == 1.0 and s["max_drawdown"] == -100
    assert list(with_pnl(t)["r_multiple"].round(2).head(2)) == [2.0, -2.0]
    print("ok")
