"""Opportunity scanner: run the setup engine over a whole universe of shares and keep the ones that meet the user's
reward:risk. Daily candles in one batch download; option chains only for the few best F&O names.

Ranking is transparency, not prediction: confirmations = trend (price vs EMA 200), signal score sign, MACD side,
Supertrend side, each agreeing with the setup's direction. Timing tells *when* the plan applies: now (momentum),
on a pullback to the entry, or on a close beyond the breakout level.
"""
import math
from datetime import datetime, time

import pandas as pd
import yfinance as yf

import data
import signals
import vatsal
from setups import option_legs, setup_verdict, underlying_setups

WHEN = {"Momentum": "Now, at market", "Pullback": "Wait for a pullback to the entry", "Breakout": "Only on a close beyond the level"}


def market_status(now=None):
    """NSE cash market hours (IST): 09:15-15:30, Mon-Fri. ponytail: ignores exchange holidays."""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return "closed", "Weekend: plans below use the last close. Re-scan after 09:15 on the next trading day."
    t = now.time()
    if t < time(9, 15):
        return "pre-open", "Before 09:15: levels are from yesterday's close. Many traders wait for the first 15 minutes to settle."
    if t <= time(9, 30):
        return "open", "First 15 minutes: spreads are wide and moves are noisy. Many traders wait until after 09:30."
    if t <= time(15, 30):
        return "open", "Market open."
    return "closed", "After 15:30: plans below use today's close for tomorrow."


def _metrics(d, s, vmode):
    """The subset of metrics the setup engine needs, from daily candles only."""
    frame = data.indicators(d, s)
    last = frame.iloc[-1].to_dict()
    prev = d.iloc[-2]
    m = {"price": float(d["Close"].iloc[-1]), "close": float(d["Close"].iloc[-1]), **last, **signals.daily(d, frame),
         "day_high": float(d["High"].iloc[-1]), "day_low": float(d["Low"].iloc[-1]),
         "high_52w": float(d["High"].tail(252).max()), "low_52w": float(d["Low"].tail(252).min()),
         "change_pct": float((d["Close"].iloc[-1] / prev["Close"] - 1) * 100)}
    m |= signals.score(m)
    if vmode:
        m |= {f"pivot_{k.lower()}": v for k, v in vatsal.pivots(prev["High"], prev["Low"], prev["Close"]).items()}
        m |= vatsal.summary(d, s["vatsal"])
    return m


def confirmations(m, side):
    sgn = 1 if side == "LONG" else -1
    checks = {
        "trend": (m["close"] - m.get("ema_200", m["close"])) * sgn > 0,
        "signals": m.get("sig_score", 0) * sgn > 0,
        "macd": (m.get("macd", 0) - m.get("macd_signal", 0)) * sgn > 0,
        "supertrend": m.get("supertrend_dir", 0) * sgn > 0,
    }
    return sum(checks.values()), [k for k, ok in checks.items() if ok]


def size(entry, stop, capital, risk_pct):
    """Shares so that hitting the stop loses risk_pct of capital (and the position fits in capital)."""
    per_share = abs(entry - stop)
    if not capital or not risk_pct or per_share <= 0:
        return None
    return max(0, min(math.floor(capital * risk_pct / 100 / per_share), math.floor(capital / entry)))


def scan(symbols, min_rr=2.0, capital=None, risk_pct=1.0, vmode=False, direction="Both", progress=None):
    """Returns (DataFrame of qualifying setups, list of symbols that failed to load)."""
    s = data.load_settings()
    tickers = [f"{x}.NS" for x in symbols]
    raw = yf.download(tickers, period="1y", interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=False)
    rows, failed = [], []
    for n, sym in enumerate(symbols):
        if progress:
            progress((n + 1) / len(symbols), sym)
        try:
            d = (raw[f"{sym}.NS"] if len(tickers) > 1 else raw).dropna()
            if len(d) < 60:
                raise ValueError("not enough history")
            m = _metrics(d, s, vmode)
        except Exception:
            failed.append(sym)
            continue
        bias = 1 if m["close"] > m.get("ema_200", m["close"]) else -1
        for st in underlying_setups(m, m["atr"], vmode):
            if direction != "Both" and st["side"] != direction.upper():
                continue
            act, why = setup_verdict(st, bias)
            if act == "AVOID" or st["rr"] < min_rr:
                continue
            conf, which = confirmations(m, st["side"])
            qty = size(st["entry"], st["stop"], capital, risk_pct)
            rows.append({
                "symbol": sym, "action": act, "setup": st["kind"], "when": WHEN[st["kind"]],
                "entry": st["entry"], "stop": st["stop"], "target": st["t1"], "target2": st["t2"], "rr": st["rr"],
                "confirm": conf, "agrees": ", ".join(which) or "-", "price": round(m["price"], 2),
                "change_pct": round(m["change_pct"], 2), "sig_score": m["sig_score"], "rsi": round(m["rsi"], 1),
                "risk_pct": st["risk_pct"], "qty": qty, "capital_used": qty and round(qty * st["entry"], 0),
                "max_loss": qty and round(qty * abs(st["entry"] - st["stop"]), 0),
                "why": f"{st['entry_why']}; stop {st['stop_why']}; target {st['t1_why']}",
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["confirm", "rr"], ascending=False, ignore_index=True)
    return df, failed


def with_options(df, fo_symbols, top=5, cfg=None):
    """Attach the ATM-ish option leg (CE for BUY, PE for SELL) to the best `top` F&O rows."""
    cfg = cfg or data.load_settings()["option_pick"]
    out = []
    for _, r in df[df["symbol"].isin(fo_symbols)].head(top).iterrows():
        try:
            om = data.option_metrics(r["symbol"])
        except Exception:
            continue
        setup = {"side": "LONG" if r["action"] == "BUY" else "SHORT", "entry": r["entry"], "stop": r["stop"], "t1": r["target"]}
        legs = option_legs(setup, om["_chain"], om["spot"], om["expiry"], cfg)
        leg = next((l for l in legs if l["label"] == "ATM"), legs[0] if legs else None)
        if leg:
            out.append({"symbol": r["symbol"], "option": f"{r['symbol']} {leg['strike']:g} {leg['kind']}", "expiry": om["expiry"],
                        "buy_at": leg["prem_entry"], "stop": leg["prem_stop"], "target": leg["prem_t1"], "rr": leg["rr"],
                        "delta": leg["delta"], "iv": leg["iv"], "underlying_plan": f"{r['action']} {r['setup']}: {r['when']}"})
    return pd.DataFrame(out)
