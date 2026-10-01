"""Backtest a rules.toml advisor on daily candles. Replays history bar by bar, so no lookahead.

Each bar's metrics come from only the candles up to that bar's close (the same daily metrics the scanner uses).
The verdict at a close is acted on at the NEXT bar's open. Long label enters long / exits a short, short label
enters short / exits a long. Optional stop and target are ATR multiples from the fill, checked on each bar's
high/low; a gap through them fills at the open, and a bar touching both counts as the stop (conservative).
Intraday, options, fundamentals and market metrics have no free history, so rules using them never pass here.
"""
import pandas as pd
import yfinance as yf

import data
import scanner
from advisor import verdict

WARMUP = 200  # bars before the first verdict, so EMA 200 has settled


def history(symbol, exchange="NSE", period="3y"):
    return yf.Ticker(data.yf_symbol(symbol, exchange)).history(period=period)


def verdicts(d, section, s, vmode=False, progress=None):
    """Verdict label at each bar's close, plus the metric names the rules asked for but the history can't supply."""
    out, missing, n = {}, set(), len(d)
    for i in range(WARMUP, n):
        m = scanner._metrics(d.iloc[:i + 1], s, vmode)
        v = verdict(section, m)
        out[d.index[i]] = v["verdict"]
        missing |= {x for cs in v["checks"].values() for c in cs for x in (c["metric"], c["value"]) if isinstance(x, str) and x not in m}
        if progress and i % 20 == 0:
            progress((i - WARMUP) / (n - WARMUP), d.index[i])
    return pd.Series(out, dtype=object), sorted(missing)


def simulate(d, labels, atr, long_label="BUY", short_label="SELL", shorts=False, stop_atr=0, target_atr=0, cost_pct=0.1):
    """Trades and a daily equity curve (starts at 1, fully invested per trade, compounding). cost_pct is per side."""
    o, h, l, c = (d[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx, pos, trades, eq, equity = d.index, None, [], 1.0, []
    labels = labels.reindex(idx)

    def close(i, px, why):
        nonlocal pos, eq
        ret = (px / pos["entry"] - 1) * pos["side"] - 2 * cost_pct / 100
        eq = pos["eq0"] * (1 + ret)
        trades.append({"side": "LONG" if pos["side"] > 0 else "SHORT", "entry_date": idx[pos["i"]].date(), "entry": round(pos["entry"], 2),
                       "exit_date": idx[i].date(), "exit": round(px, 2), "bars": i - pos["i"], "ret_pct": round(ret * 100, 2), "exit_why": why})
        pos = None

    for i in range(len(d)):
        sig = labels.iloc[i - 1] if i else None  # yesterday's close decides today's open
        want = 1 if sig == long_label else -1 if (sig == short_label and shorts) else 0
        if pos and sig in (long_label, short_label) and (1 if sig == long_label else -1) != pos["side"]:
            close(i, o[i], f"{sig} signal")
        if not pos and want:
            a = atr.iloc[i - 1]
            pos = {"side": want, "i": i, "entry": o[i], "eq0": eq,
                   "stop": o[i] - want * stop_atr * a if stop_atr else None, "target": o[i] + want * target_atr * a if target_atr else None}
        if pos:
            sd, st_, tg = pos["side"], pos["stop"], pos["target"]
            if st_ is not None and (l[i] <= st_ if sd > 0 else h[i] >= st_):
                close(i, min(o[i], st_) if sd > 0 else max(o[i], st_), "stop")
            elif tg is not None and (h[i] >= tg if sd > 0 else l[i] <= tg):
                close(i, max(o[i], tg) if sd > 0 else min(o[i], tg), "target")
        equity.append(pos["eq0"] * (1 + (c[i] / pos["entry"] - 1) * pos["side"] - cost_pct / 100) if pos else eq)
    if pos:
        close(len(d) - 1, c[-1], "still open (marked at last close)")
        equity[-1] = eq
    return pd.DataFrame(trades), pd.Series(equity, index=idx)


def stats(trades, equity, d):
    r = trades["ret_pct"] if len(trades) else pd.Series(dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    years = max((d.index[-1] - d.index[0]).days / 365.25, 1e-9)
    total = equity.iloc[-1] - 1
    return {
        "trades": len(r), "win_rate": len(wins) / len(r) * 100 if len(r) else None,
        "avg_win": wins.mean() if len(wins) else None, "avg_loss": losses.mean() if len(losses) else None,
        "profit_factor": wins.sum() / -losses.sum() if losses.sum() < 0 else None,
        "total_ret": total * 100, "cagr": ((1 + total) ** (1 / years) - 1) * 100 if total > -1 else -100,
        "max_dd": ((equity / equity.cummax()) - 1).min() * 100,
        "buy_hold": (d["Close"].iloc[-1] / d["Open"].iloc[0] - 1) * 100,
        "exposure": trades["bars"].sum() / len(d) * 100 if len(trades) else 0,
    }


def run(symbol, section, exchange="NSE", period="3y", vmode=False, progress=None, **sim):
    """History -> verdicts -> trades. The trade window starts after WARMUP bars, and buy & hold is measured on it too."""
    d = history(symbol, exchange, period)
    if len(d) <= WARMUP + 20:
        raise ValueError(f"only {len(d)} daily candles for {symbol}; need more than {WARMUP + 20}. Pick a longer period.")
    s = data.load_settings()
    labels, missing = verdicts(d, section, s, vmode, progress)
    atr = data.indicators(d, s)["atr"]
    w = d.iloc[WARMUP:]
    trades, equity = simulate(w, labels, atr.iloc[WARMUP:], **sim)
    return {"d": w, "labels": labels, "trades": trades, "equity": equity, "stats": stats(trades, equity, w), "missing": missing}


if __name__ == "__main__":  # offline self-check on a synthetic series
    idx = pd.bdate_range("2024-01-01", periods=6)
    px = [100, 110, 120, 110, 100, 100]
    d = pd.DataFrame({"Open": px, "High": [p + 1 for p in px], "Low": [p - 1 for p in px], "Close": px}, index=idx)
    lab = pd.Series(["BUY", "HOLD", "SELL", "HOLD", "HOLD", "HOLD"], index=idx)
    atr = pd.Series(5.0, index=idx)
    t, eq = simulate(d, lab, atr, cost_pct=0)
    assert len(t) == 1 and t.iloc[0]["entry"] == 110 and t.iloc[0]["exit"] == 110 and t.iloc[0]["ret_pct"] == 0  # next-open fills
    t, eq = simulate(d, lab, atr, shorts=True, cost_pct=0)
    assert list(t["side"]) == ["LONG", "SHORT"] and abs(t.iloc[1]["ret_pct"] - 9.09) < 0.01  # short 110 -> marked 100
    t, _ = simulate(d, lab, atr, target_atr=1, cost_pct=0)
    assert t.iloc[0]["exit_why"] == "target" and t.iloc[0]["exit"] == 120  # target 115, but day 3 gaps up to open 120
    t, _ = simulate(d, pd.Series("BUY", index=idx).where(idx == idx[2], "HOLD"), atr, stop_atr=1, cost_pct=0)
    assert t.iloc[0]["exit_why"] == "stop" and t.iloc[0]["exit"] == 100  # stop 105, but day 5 gaps down to open 100
    print("ok")
