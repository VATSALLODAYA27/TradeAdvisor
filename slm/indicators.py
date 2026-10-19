"""Indicators with the PRD's fixed parameters (TradingView conventions: Wilder smoothing)."""
import numpy as np
import pandas as pd


def sma(c, n):
    return c.rolling(n).mean()


def ema(c, n):
    return c.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / down.replace(0, np.nan))).where(down > 0, 100.0)  # no down moves → RSI 100


def atr(d, n=10):
    h, l, c = d["High"], d["Low"], d["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(d, n=10, mult=3.0):
    """Direction series: 1 = up (bullish), -1 = down (bearish)."""
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    a = atr(d, n).to_numpy()
    hl2 = (h + l) / 2
    up, dn = hl2 - mult * a, hl2 + mult * a
    fu, fd, out = up.copy(), dn.copy(), np.ones(len(c), dtype=int)
    for i in range(1, len(c)):
        fu[i] = max(up[i], fu[i - 1]) if c[i - 1] > fu[i - 1] else up[i]
        fd[i] = min(dn[i], fd[i - 1]) if c[i - 1] < fd[i - 1] else dn[i]
        out[i] = 1 if c[i] > fd[i - 1] else -1 if c[i] < fu[i - 1] else out[i - 1]
    return pd.Series(out, index=d.index)


def weekly(d):
    return d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
