"""Order blocks, resting liquidity and the X-Ray board (every stock ranked Bullish / Bearish / Choppy).

Textbook price-action definitions on free candles, nothing proprietary and no order-book data:
  order block : the candle a move started from, once that move closes beyond the previous swing high (bullish) or
                swing low (bearish). It stays live until a later candle closes through its far side.
  liquidity   : swing highs / lows that price has not traded through yet, where stop orders usually rest.
  sweep (trap): a candle that pierces such a level and closes back inside it.
  strength    : today's move in ATRs x how straight the move was (net move / distance travelled).
All functions take an OHLCV DataFrame (columns Open/High/Low/Close/Volume) and return plain Python data.
"""
import numpy as np
import pandas as pd
import yfinance as yf

from vatsal import _pivot_points

SWING = 5          # bars on each side that make a swing high / low
CHOPPY_EFF = 0.25  # below this share of the travelled distance kept as net move, the day is choppy (15m bars)
MIN_MOVE = 0.3     # ...and so is a move smaller than this many ATRs
SWEEP_BARS = 8     # a sweep counts as recent for this many bars


def order_blocks(d, swing=SWING):
    """Live zones [{kind: ob_bull|ob_bear, start, top, bottom, broke}], oldest first."""
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    out = {}
    for kind, pts in (("ob_bull", _pivot_points(h, swing, swing, "H")), ("ob_bear", _pivot_points(l, swing, swing, "L"))):
        up = kind == "ob_bull"
        for i in pts:
            hits = np.flatnonzero(c[i + 1:] > h[i] if up else c[i + 1:] < l[i])
            if not len(hits):
                continue  # structure not broken yet
            k = i + 1 + int(hits[0])
            # the origin of the move: the lowest candle (highest for a bearish block) between the swing and the break
            j = i + 1 + int(l[i + 1:k].argmin() if up else h[i + 1:k].argmax())
            top, bottom = float(h[j]), float(l[j])
            if (c[k + 1:] < bottom).any() if up else (c[k + 1:] > top).any():
                continue  # price closed through it: no longer a block
            out[kind, j] = {"kind": kind, "start": j, "top": top, "bottom": bottom, "broke": k}
    return sorted(out.values(), key=lambda z: z["start"])


def liquidity(d, swing=SWING):
    """(resting levels [{side: +1 above highs | -1 below lows, start, price}],
        sweeps [{side, at, price}] where a candle pierced a level and closed back inside)."""
    h, l, c = d["High"].to_numpy(), d["Low"].to_numpy(), d["Close"].to_numpy()
    resting, sweeps = [], []
    for side, pts in ((1, _pivot_points(h, swing, swing, "H")), (-1, _pivot_points(l, swing, swing, "L"))):
        for i in pts:
            p = float(h[i] if side > 0 else l[i])
            hits = np.flatnonzero(h[i + 1:] > p if side > 0 else l[i + 1:] < p)
            if not len(hits):
                resting.append({"side": side, "start": i, "price": p})
                continue
            k = i + 1 + int(hits[0])
            if (c[k] < p) if side > 0 else (c[k] > p):
                sweeps.append({"side": side, "at": k, "price": p})
    return resting, sorted(sweeps, key=lambda s: s["at"])


def levels(d, swing=SWING):
    """The zones in play around the last price, as flat values for the board and the levels card."""
    price = float(d["Close"].iloc[-1])
    obs = order_blocks(d, swing)
    resting, sweeps = liquidity(d, swing)
    bull = max((z for z in obs if z["kind"] == "ob_bull" and z["bottom"] <= price), key=lambda z: z["top"], default=None)
    bear = min((z for z in obs if z["kind"] == "ob_bear" and z["top"] >= price), key=lambda z: z["bottom"], default=None)
    recent = [s for s in sweeps if s["at"] >= len(d) - SWEEP_BARS]
    inside = lambda z: bool(z) and z["bottom"] <= price <= z["top"]
    return {
        "price": price,
        "ob_bull_top": bull and bull["top"], "ob_bull_bottom": bull and bull["bottom"],
        "ob_bear_bottom": bear and bear["bottom"], "ob_bear_top": bear and bear["top"],
        "in_ob": 1 if inside(bull) else -1 if inside(bear) else 0,
        "liq_above": min((x["price"] for x in resting if x["side"] > 0 and x["price"] > price), default=None),
        "liq_below": max((x["price"] for x in resting if x["side"] < 0 and x["price"] < price), default=None),
        # highs swept and rejected = buyers trapped (-1); lows swept and reclaimed = sellers trapped (+1)
        "sweep": -recent[-1]["side"] if recent else 0,
        "sweep_price": recent[-1]["price"] if recent else None,
    }


def xray(d, swing=SWING):
    """One board row from ~1 month of 15-minute candles: side, strength and the zones in play."""
    day = np.array(d.index.date)
    days = d.groupby(day).agg(High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"))
    if len(days) < 5:
        raise ValueError("not enough history")
    prev = float(days["Close"].iloc[-2])
    tr = pd.concat([days["High"] - days["Low"], (days["High"] - days["Close"].shift()).abs(),
                    (days["Low"] - days["Close"].shift()).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.iloc[:-1].tail(14).mean()) / prev * 100  # completed sessions only
    price = float(d["Close"].iloc[-1])
    change = (price / prev - 1) * 100
    path = np.concatenate([[prev], d["Close"].to_numpy()[day == day[-1]]])  # yesterday's close through today's bars
    travelled = float(np.abs(np.diff(path)).sum())
    eff = abs(price - prev) / travelled if travelled else 0.0
    move = change / atr_pct if atr_pct else 0.0
    side = "Choppy" if eff < CHOPPY_EFF or abs(move) < MIN_MOVE else "Bullish" if move > 0 else "Bearish"
    return {"side": side, "strength": round(abs(move) * eff * 100), "change_pct": round(change, 2), "move_atr": round(move, 2),
            "efficiency": round(eff, 2), "atr_pct": round(atr_pct, 2), **levels(d, swing)}


def scan(symbols):
    """Returns (DataFrame of board rows, strongest first; symbols that failed to load)."""
    tickers = [f"{x}.NS" for x in symbols]
    # ponytail: Yahoo 15m bars lag a few minutes; a live board needs a paid broker feed
    raw = yf.download(tickers, period="1mo", interval="15m", group_by="ticker", threads=True, progress=False, auto_adjust=False)
    rows, failed = [], []
    for sym in symbols:
        try:
            rows.append({"symbol": sym, **xray((raw[f"{sym}.NS"] if len(tickers) > 1 else raw).dropna())})
        except Exception:
            failed.append(sym)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("strength", ascending=False, ignore_index=True)
    return df, failed
