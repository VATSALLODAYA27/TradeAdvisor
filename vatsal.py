"""Vatsal's indicator: a Python port of the user's TradingView "All Indicator Combo - Tradefinder" setup.

Signal (per bar):
  trigger   : EMA fast crosses EMA slow (MA1/MA2 = 5/13).  ASSUMPTION: the Tradefinder "leading indicator"
              (settings section 03) was not shared; swap `trigger` below once it is known.
  confirm   : EMA filter (close vs EMA 200) AND 2-EMA cross state (EMA 50 vs EMA 200, cross within `cross_lookback`
              bars counts as fresh, otherwise the state must simply agree)
  expiry    : a trigger stays armed for `signal_expiry` candles waiting for the confirmations
  alternate : a signal must alternate direction (no BUY after BUY)
Overlays: auto-Fibonacci (0/0.5/1), classic pivots (P, S1-S3, R1-R3), supply/demand zones, PVSRA liquidity zones.
All functions take an OHLCV DataFrame (columns Open/High/Low/Close/Volume) and return plain Python data.
"""
import numpy as np
import pandas as pd

DEFAULTS = {
    "emas": [5, 13, 50, 200],   # 06: MA lines shown when Vatsal's indicator is on (MA3 = 20 is off)
    "trigger": [5, 13],         # MA1 / MA2 cross = leading trigger (assumption, see above)
    "ema_filter": 200,          # 04: EMA Filter
    "cross": [50, 200],         # 04: 2 EMA Cross
    "cross_lookback": 3,
    "signal_expiry": 3,         # 02: Signal Expiry Candle Count
    "alternate": True,          # 02: Alternate Signal
    "fib_deviation": 3,         # 05: Fibonacci
    "fib_depth": 10,
    "fib_levels": [0, 0.5, 1],
    "sd_swing": 10,             # 46: Supply/Demand Zone
    "sd_history": 20,
    "sd_box_width": 2.5,
    "liq_max_zones": 500,       # 49: Liquidity Zone
    "fvg": True,                # Fair Value Gap: ON (confirmed by the user)
    "fvg_show": 10,             # most recent unfilled gaps drawn on the chart
}


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(d, n):
    c = d["Close"]
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - c.shift()).abs(), (d["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


# ---------------- signal ----------------

def signals(d, cfg):
    """DataFrame with bias (+1/-1/0 from the two filters) and signal (+1 BUY / -1 SELL on the bar it fires)."""
    c = d["Close"]
    f1, f2 = (ema(c, n) for n in cfg["trigger"])
    filt = ema(c, cfg["ema_filter"])
    fast, slow = (ema(c, n) for n in cfg["cross"])
    above = (f1 > f2).astype(int)
    trig = above.diff().fillna(0)  # +1 golden cross of the trigger EMAs, -1 death cross
    state = np.sign(fast - slow)
    bias = pd.Series(np.where((c > filt) & (state > 0), 1, np.where((c < filt) & (state < 0), -1, 0)), index=d.index)

    out, armed, armed_age, last = [], 0, 0, 0
    for t, b in zip(trig.to_numpy(), bias.to_numpy()):
        if t != 0:
            armed, armed_age = int(t), 0
        elif armed:
            armed_age += 1
            if armed_age > cfg["signal_expiry"]:
                armed = 0
        fire = armed if armed and b == armed and not (cfg["alternate"] and armed == last) else 0
        if fire:
            last, armed = fire, 0
        out.append(fire)
    sig = pd.Series(out, index=d.index)
    cross_age = _bars_since(state.diff().fillna(0) != 0)
    return pd.DataFrame({"bias": bias, "signal": sig, "cross_age": cross_age}, index=d.index)


def _bars_since(flags):
    out, n = [], None
    for f in flags.to_numpy():
        n = 0 if f else (None if n is None else n + 1)
        out.append(n)
    return pd.Series(out, index=flags.index)


def last_signal(sig):
    """(direction, bars ago, index) of the most recent signal, or (0, None, None)."""
    nz = np.flatnonzero(sig.to_numpy())
    if not len(nz):
        return 0, None, None
    i = int(nz[-1])
    return int(sig.iloc[i]), len(sig) - 1 - i, i


# ---------------- levels ----------------

def pivots(h, l, c):
    """Classic floor pivots from one completed period's high/low/close."""
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l),
            "R3": h + 2 * (p - l), "S3": l - 2 * (h - p)}


def _pivot_points(values, left, right, kind):
    """Indices where values[i] is the max/min of [i-left, i+right]: strictly beyond the left side, ties allowed on the
    right, so a flat top counts once at its first bar (TradingView ta.pivothigh/low behaviour)."""
    v = np.asarray(values, dtype=float)
    idx = []
    for i in range(left, len(v) - right):
        lft, rgt = v[i - left:i], v[i + 1:i + right + 1]
        if kind == "H" and (lft < v[i]).all() and (rgt <= v[i]).all():
            idx.append(i)
        elif kind == "L" and (lft > v[i]).all() and (rgt >= v[i]).all():
            idx.append(i)
    return idx


def zigzag(d, depth, deviation):
    """Alternating swing points [(index, price, 'H'|'L')], like TradingView's Auto Fib Retracement zigzag."""
    half = max(1, depth // 2)
    pts = sorted([(i, d["High"].iloc[i], "H") for i in _pivot_points(d["High"], half, half, "H")] +
                 [(i, d["Low"].iloc[i], "L") for i in _pivot_points(d["Low"], half, half, "L")])
    thr = (atr(d, 10) / d["Close"] * 100 * deviation).to_numpy()  # deviation is an ATR multiplier, in %
    zz = []
    for i, p, k in pts:
        if zz and zz[-1][2] == k:
            if (k == "H" and p > zz[-1][1]) or (k == "L" and p < zz[-1][1]):
                zz[-1] = (i, p, k)
        elif not zz or abs(p / zz[-1][1] - 1) * 100 >= thr[i]:
            zz.append((i, p, k))
    return zz


def fib(d, cfg):
    """Fib levels over the last completed swing: level 0 at the latest swing point, 1 at the one before."""
    zz = zigzag(d, cfg["fib_depth"], cfg["fib_deviation"])
    if len(zz) < 2:
        return None
    (i0, p0, _), (i1, p1, k1) = zz[-2], zz[-1]
    return {"start": i0, "end": i1, "direction": "up" if k1 == "H" else "down",
            "levels": {lv: p1 + (p0 - p1) * lv for lv in cfg["fib_levels"]}}


def supply_demand(d, cfg):
    """Swing-pivot zones: height = ATR(50) * box_width / 10 (as in the Supply/Demand Zone script). Broken zones are dropped."""
    n, a = cfg["sd_swing"], atr(d, 50).to_numpy()
    close = d["Close"].to_numpy()
    zones = []
    for i in _pivot_points(d["High"], n, n, "H"):
        top = d["High"].iloc[i]
        zones.append({"kind": "supply", "start": i, "top": top, "bottom": top - a[i] * cfg["sd_box_width"] / 10})
    for i in _pivot_points(d["Low"], n, n, "L"):
        bot = d["Low"].iloc[i]
        zones.append({"kind": "demand", "start": i, "top": bot + a[i] * cfg["sd_box_width"] / 10, "bottom": bot})
    live = []
    for z in sorted(zones, key=lambda z: z["start"]):
        after = close[z["start"] + n + 1:]  # the pivot is only known n bars later
        broken = (after > z["top"]).any() if z["kind"] == "supply" else (after < z["bottom"]).any()
        if not broken:
            live.append(z)
    keep = cfg["sd_history"]
    return [z for z in live if z["kind"] == "supply"][-keep:] + [z for z in live if z["kind"] == "demand"][-keep:]


def liquidity_zones(d, cfg):
    """PVSRA vector candles (volume >= 150% / 200% of the 10-bar average) leave a body-sized zone,
    cleared once a later candle body covers it."""
    v = d["Volume"]
    if not v.sum():
        return []  # indices carry no volume
    avg = v.rolling(10).mean().shift()
    vs = v * (d["High"] - d["Low"])
    climax = (v >= 2 * avg) | (vs >= vs.rolling(10).max().shift())
    rising = (v >= 1.5 * avg) & ~climax
    o, c = d["Open"].to_numpy(), d["Close"].to_numpy()
    lo_b, hi_b = np.minimum(o, c), np.maximum(o, c)
    zones = []
    for i in np.flatnonzero((climax | rising).to_numpy()):
        top, bot = hi_b[i], lo_b[i]
        if top <= bot:
            continue
        later = slice(i + 1, None)
        cleared = ((lo_b[later] <= bot) & (hi_b[later] >= top)).any()
        if not cleared:
            zones.append({"kind": ("climax" if climax.iloc[i] else "rising") + ("_up" if c[i] >= o[i] else "_down"),
                          "start": int(i), "top": float(top), "bottom": float(bot)})
    return zones[-cfg["liq_max_zones"]:]


def fair_value_gaps(d, cfg):
    """3-candle imbalances. Bullish: low[i] > high[i-2] (gap = high[i-2]..low[i]). Bearish: high[i] < low[i-2].
    A gap is filled (dropped) once a later candle trades back through it completely."""
    if not cfg.get("fvg", True):
        return []
    h, l = d["High"].to_numpy(), d["Low"].to_numpy()
    gaps = []
    for i in range(2, len(d)):
        if l[i] > h[i - 2]:
            gaps.append({"kind": "fvg_bull", "start": i - 1, "top": float(l[i]), "bottom": float(h[i - 2])})
        elif h[i] < l[i - 2]:
            gaps.append({"kind": "fvg_bear", "start": i - 1, "top": float(l[i - 2]), "bottom": float(h[i])})
    live = []
    for g in gaps:
        later = slice(g["start"] + 2, None)
        filled = (l[later] <= g["bottom"]).any() if g["kind"] == "fvg_bull" else (h[later] >= g["top"]).any()
        if not filled:
            live.append(g)
    return live


# ---------------- summary for metrics ----------------

def nearest(levels, price):
    """(closest level above, closest level below) from a {name: price} dict."""
    above = {k: v for k, v in levels.items() if v is not None and v > price}
    below = {k: v for k, v in levels.items() if v is not None and v <= price}
    up = min(above.items(), key=lambda kv: kv[1]) if above else (None, None)
    dn = max(below.items(), key=lambda kv: kv[1]) if below else (None, None)
    return up, dn


def summary(d, cfg, prefix="vs"):
    """Flat metrics for the rules engine, computed on one timeframe."""
    sig = signals(d, cfg)
    direction, age, _ = last_signal(sig["signal"])
    price = float(d["Close"].iloc[-1])
    out = {f"{prefix}_bias": int(sig["bias"].iloc[-1]), f"{prefix}_signal": direction, f"{prefix}_signal_age": age,
           f"{prefix}_cross_age": sig["cross_age"].iloc[-1]}
    if prefix != "vs":
        return out
    f = fib(d, cfg)
    if f:
        out |= {f"fib_{str(k).replace('.', '')}": v for k, v in f["levels"].items()}
    sd = supply_demand(d, cfg)
    sup = [z for z in sd if z["kind"] == "supply" and z["bottom"] > price]
    dem = [z for z in sd if z["kind"] == "demand" and z["top"] < price]
    s_near = min(sup, key=lambda z: z["bottom"]) if sup else None
    d_near = max(dem, key=lambda z: z["top"]) if dem else None
    out |= {
        "supply_bottom": s_near and s_near["bottom"], "supply_top": s_near and s_near["top"],
        "demand_top": d_near and d_near["top"], "demand_bottom": d_near and d_near["bottom"],
        "in_supply": int(any(z["bottom"] <= price <= z["top"] for z in sd if z["kind"] == "supply")),
        "in_demand": int(any(z["bottom"] <= price <= z["top"] for z in sd if z["kind"] == "demand")),
    }
    fv = fair_value_gaps(d, cfg)
    bull = [g for g in fv if g["kind"] == "fvg_bull" and g["top"] < price]   # support gaps below
    bear = [g for g in fv if g["kind"] == "fvg_bear" and g["bottom"] > price]  # resistance gaps above
    b_near = max(bull, key=lambda g: g["top"]) if bull else None
    s_near = min(bear, key=lambda g: g["bottom"]) if bear else None
    out |= {
        "fvg_bull_top": b_near and b_near["top"], "fvg_bull_bottom": b_near and b_near["bottom"],
        "fvg_bear_bottom": s_near and s_near["bottom"], "fvg_bear_top": s_near and s_near["top"],
        "in_fvg": int(any(g["bottom"] <= price <= g["top"] for g in fv)),
    }
    return out
