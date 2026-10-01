"""Named technical signals (breakouts, breakdowns, MACD/RSI/Supertrend events ...) as 0/1 metrics.

Each becomes a metric `sig_<key>` usable in rules, plus sig_bull / sig_bear counts and sig_score = bull - bear.
Daily candles unless the label says intraday. "Recent" = within the last RECENT bars.
"""
import pandas as pd

RECENT = 3
LOOKBACK = 20  # bars for the resistance / support used by the break signals

SIGNALS = [  # key, side, label
    ("resistance_break", "bull", "Bullish resistance break (close above the 20-day high)"),
    ("high_52w_break", "bull", "52-week high breakout"),
    ("macd_above_signal", "bull", "MACD above signal line"),
    ("macd_bull_cross", "bull", "MACD crossed above signal (recent)"),
    ("rsi_oversold", "bull", "RSI oversold (< 30)"),
    ("rsi_bull_reversal", "bull", "RSI back above 30 from oversold (recent)"),
    ("golden_cross", "bull", "Golden cross: EMA 50 above EMA 200 (last 10 bars)"),
    ("supertrend_up", "bull", "Supertrend up"),
    ("supertrend_flip_up", "bull", "Supertrend flipped up (recent)"),
    ("volume_breakout", "bull", "Up day on 1.5× average volume"),
    ("bb_lower_touch", "bull", "Close at/below lower Bollinger Band"),
    ("above_vwap", "bull", "Intraday: price above VWAP"),
    ("orb_breakout", "bull", "Intraday: opening-range breakout"),
    ("support_break", "bear", "Bearish support break (close below the 20-day low)"),
    ("low_52w_break", "bear", "52-week low breakdown"),
    ("macd_below_signal", "bear", "MACD below signal line"),
    ("macd_bear_cross", "bear", "MACD crossed below signal (recent)"),
    ("rsi_overbought", "bear", "RSI overbought (> 70)"),
    ("rsi_bear_reversal", "bear", "RSI back below 70 from overbought (recent)"),
    ("death_cross", "bear", "Death cross: EMA 50 below EMA 200 (last 10 bars)"),
    ("supertrend_down", "bear", "Supertrend down"),
    ("supertrend_flip_down", "bear", "Supertrend flipped down (recent)"),
    ("volume_breakdown", "bear", "Down day on 1.5× average volume"),
    ("bb_upper_touch", "bear", "Close at/above upper Bollinger Band"),
    ("below_vwap", "bear", "Intraday: price below VWAP"),
    ("orb_breakdown", "bear", "Intraday: opening-range breakdown"),
]
KEYS = [f"sig_{k}" for k, _, _ in SIGNALS]


def _crossed(a, b, bars):
    """a crossed above b within the last `bars` bars."""
    up = (a > b) & (a.shift() <= b.shift())
    return bool(up.tail(bars).any())


def daily(d, ind):
    """Daily-candle signals. d: OHLCV frame; ind: data.indicators() frame on the same index."""
    c, v = d["Close"], d["Volume"]
    e50, e200 = c.ewm(span=50, adjust=False).mean(), c.ewm(span=200, adjust=False).mean()
    hh, ll = d["High"].shift().rolling(LOOKBACK).max(), d["Low"].shift().rolling(LOOKBACK).min()
    macd, sig, rsi, st = ind["macd"], ind["macd_signal"], ind["rsi"], ind["supertrend_dir"]
    up_day = c.iloc[-1] > c.iloc[-2]
    vol_hi = bool(v.iloc[-1]) and ind["vol_ratio"].iloc[-1] >= 1.5
    flags = {
        "resistance_break": c.iloc[-1] > hh.iloc[-1],
        "support_break": c.iloc[-1] < ll.iloc[-1],
        "high_52w_break": c.iloc[-1] > d["High"].shift().rolling(252, min_periods=60).max().iloc[-1],
        "low_52w_break": c.iloc[-1] < d["Low"].shift().rolling(252, min_periods=60).min().iloc[-1],
        "macd_above_signal": macd.iloc[-1] > sig.iloc[-1],
        "macd_below_signal": macd.iloc[-1] < sig.iloc[-1],
        "macd_bull_cross": _crossed(macd, sig, RECENT),
        "macd_bear_cross": _crossed(sig, macd, RECENT),
        "rsi_oversold": rsi.iloc[-1] < 30,
        "rsi_overbought": rsi.iloc[-1] > 70,
        "rsi_bull_reversal": _crossed(rsi, pd.Series(30.0, index=rsi.index), RECENT),
        "rsi_bear_reversal": _crossed(pd.Series(70.0, index=rsi.index), rsi, RECENT),
        "golden_cross": _crossed(e50, e200, 10),
        "death_cross": _crossed(e200, e50, 10),
        "supertrend_up": st.iloc[-1] == 1,
        "supertrend_down": st.iloc[-1] == -1,
        "supertrend_flip_up": _crossed(st, pd.Series(0.0, index=st.index), RECENT),
        "supertrend_flip_down": _crossed(pd.Series(0.0, index=st.index), st, RECENT),
        "volume_breakout": vol_hi and up_day,
        "volume_breakdown": vol_hi and not up_day,
        "bb_lower_touch": c.iloc[-1] <= ind["bb_lower"].iloc[-1],
        "bb_upper_touch": c.iloc[-1] >= ind["bb_upper"].iloc[-1],
    }
    return {f"sig_{k}": int(bool(x)) for k, x in flags.items()} | {
        "resistance_20d": float(hh.iloc[-1]), "support_20d": float(ll.iloc[-1])}


def intraday(m):
    """Signals that need the live intraday metrics (price, VWAP, opening range)."""
    p, vw = m.get("price"), m.get("vwap")
    out = {}
    if p is not None and vw is not None:
        out |= {"sig_above_vwap": int(p > vw), "sig_below_vwap": int(p < vw)}
    if p is not None and m.get("orb_high") is not None:
        out |= {"sig_orb_breakout": int(p > m["orb_high"]), "sig_orb_breakdown": int(p < m["orb_low"])}
    return out


def score(m):
    bull = sum(m.get(f"sig_{k}") == 1 for k, side, _ in SIGNALS if side == "bull")
    bear = sum(m.get(f"sig_{k}") == 1 for k, side, _ in SIGNALS if side == "bear")
    return {"sig_bull": bull, "sig_bear": bear, "sig_score": bull - bear}
