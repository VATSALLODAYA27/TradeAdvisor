"""Offline checks for orderblock.py on synthetic candles."""
import numpy as np
import pandas as pd

import orderblock as ob


def frame(close, index=None):
    close = np.asarray(close, dtype=float)
    opn = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"Open": opn, "High": np.maximum(opn, close) + 0.2, "Low": np.minimum(opn, close) - 0.2,
                         "Close": close, "Volume": 1000.0},
                        index=index if index is not None else pd.date_range("2024-01-01", periods=len(close), freq="D"))


# --- rally to 110, pullback to 104, then a break above the swing high: one bullish block at the pullback low ---
up = np.concatenate([np.linspace(100, 110, 11), np.linspace(109, 104, 6), np.linspace(105, 116, 12)])
d = frame(up)
blocks = ob.order_blocks(d)
assert [z["kind"] for z in blocks] == ["ob_bull"]
z = blocks[0]
assert z["start"] == int(np.argmin(d["Low"].to_numpy()[11:17])) + 11 and z["bottom"] == d["Low"].iloc[z["start"]]
assert d["Close"].iloc[z["broke"]] > d["High"].iloc[10]   # the break closed above the swing high

# --- the same block disappears once price closes below it ---
assert not any(b["kind"] == "ob_bull" for b in ob.order_blocks(frame(np.concatenate([up, np.linspace(115, 100, 10)]))))

# --- mirror image gives a bearish block ---
assert [b["kind"] for b in ob.order_blocks(frame(220 - up))] == ["ob_bear"]

# --- liquidity: an untouched swing high rests; a wick through it that closes back is a sweep ---
flat = np.concatenate([np.linspace(100, 110, 11), np.linspace(109, 104, 6), np.full(8, 105.0)])
d = frame(flat)
resting, sweeps = ob.liquidity(d)
top = float(d["High"].iloc[10])
assert any(x["side"] == 1 and x["price"] == top for x in resting) and not sweeps
d.iloc[-1, d.columns.get_loc("High")] = top + 1            # pierce the high, close stays at 105
resting, sweeps = ob.liquidity(d)
assert not any(x["price"] == top for x in resting) and sweeps[-1] == {"side": 1, "at": len(d) - 1, "price": top}
assert ob.levels(d)["sweep"] == -1                         # buyers trapped

# --- x-ray: a straight up day is Bullish, a whipsaw day that ends flat is Choppy ---
idx = pd.date_range("2024-01-01 09:15", periods=25, freq="15min")
days = [idx + pd.Timedelta(days=n) for n in range(8)]
wiggle = 100 + np.tile([0, 1, 0, -1], 7)[:25]
base = np.concatenate([wiggle] * 7)
trend = frame(np.concatenate([base, np.linspace(100.2, 103, 25)]), days[0].append(days[1:]))
chop = frame(np.concatenate([base, wiggle]), days[0].append(days[1:]))
t, c = ob.xray(trend), ob.xray(chop)
assert t["side"] == "Bullish" and t["efficiency"] > 0.9 and t["strength"] > c["strength"]
assert c["side"] == "Choppy"
print("ok")
