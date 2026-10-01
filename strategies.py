"""Option strategies: preset builders, payoff at expiry, value today (Black-Scholes), and the key numbers.

A leg is {"side": +1 buy / -1 sell, "kind": "CE"|"PE", "strike": float, "premium": float, "iv": %, "lots": int}.
P&L is per the whole position in ₹: side × lots × lot_size × (option value − premium paid).
"""
import math

import numpy as np

from setups import bs_price

PRESETS = {
    "Long call": "Bullish. Pay a premium; profit if price rises above strike + premium. Loss limited to the premium.",
    "Long put": "Bearish. Pay a premium; profit if price falls below strike − premium. Loss limited to the premium.",
    "Bull call spread": "Moderately bullish. Buy a call, sell a higher call: cheaper than a long call, profit capped.",
    "Bear put spread": "Moderately bearish. Buy a put, sell a lower put: cheaper than a long put, profit capped.",
    "Long straddle": "Expecting a big move either way (e.g. results). Buy ATM call + put; needs a move larger than both premiums.",
    "Long strangle": "Big move either way, cheaper than a straddle: buy OTM call + OTM put; needs an even bigger move.",
    "Short straddle": "Expecting a quiet market. Sell ATM call + put; keep premium if price stays near the strike. UNLIMITED risk.",
    "Iron condor": "Expecting a range. Sell OTM call + put, buy further OTM wings for protection; limited profit and limited loss.",
}


def _row(chain, strike):
    return min(chain, key=lambda r: abs(r["strike"] - strike))


def leg(chain, side, kind, strike, lots=1):
    r = _row(chain, strike)
    q = r.get(kind) or {}
    return {"side": side, "kind": kind, "strike": r["strike"], "premium": q.get("ltp") or 0.0, "iv": q.get("iv") or 0.0, "lots": lots}


def build(preset, chain, spot, width=2, lots=1):
    """Legs for a preset. `width` = strikes away from ATM for the short/OTM legs (wings are 2×width)."""
    strikes = sorted(r["strike"] for r in chain)
    i = min(range(len(strikes)), key=lambda k: abs(strikes[k] - spot))
    at = lambda k: strikes[max(0, min(len(strikes) - 1, i + k))]
    w = width
    return {
        "Long call": [leg(chain, 1, "CE", at(0), lots)],
        "Long put": [leg(chain, 1, "PE", at(0), lots)],
        "Bull call spread": [leg(chain, 1, "CE", at(0), lots), leg(chain, -1, "CE", at(w), lots)],
        "Bear put spread": [leg(chain, 1, "PE", at(0), lots), leg(chain, -1, "PE", at(-w), lots)],
        "Long straddle": [leg(chain, 1, "CE", at(0), lots), leg(chain, 1, "PE", at(0), lots)],
        "Long strangle": [leg(chain, 1, "CE", at(w), lots), leg(chain, 1, "PE", at(-w), lots)],
        "Short straddle": [leg(chain, -1, "CE", at(0), lots), leg(chain, -1, "PE", at(0), lots)],
        "Iron condor": [leg(chain, -1, "CE", at(w), lots), leg(chain, 1, "CE", at(2 * w), lots),
                        leg(chain, -1, "PE", at(-w), lots), leg(chain, 1, "PE", at(-2 * w), lots)],
    }[preset]


def payoff(legs, prices, lot, t=0.0):
    """Position P&L (₹) at each price: at expiry when t=0, otherwise Black-Scholes value with t years left."""
    prices = np.asarray(prices, dtype=float)
    total = np.zeros_like(prices)
    for g in legs:
        if t > 0:
            value = np.array([bs_price(p, g["strike"], t, g["iv"], g["kind"]) for p in prices])
        else:
            value = np.maximum(prices - g["strike"], 0) if g["kind"] == "CE" else np.maximum(g["strike"] - prices, 0)
        total += g["side"] * g["lots"] * lot * (value - g["premium"])
    return total


def grid(legs, spot, points=801):
    lo = min([spot] + [g["strike"] for g in legs]) * 0.75
    hi = max([spot] + [g["strike"] for g in legs]) * 1.25
    return np.linspace(lo, hi, points)


def summary(legs, spot, lot, atm_iv, t):
    """Net premium, max profit/loss (None = unlimited), breakevens, and probability of profit at expiry.
    POP uses a lognormal price at expiry with the ATM IV (risk-neutral estimate, not a forecast)."""
    xs = grid(legs, spot)
    pl = payoff(legs, xs, lot)
    net = sum(-g["side"] * g["premium"] * g["lots"] * lot for g in legs)  # >0 = credit received
    # beyond the grid the payoff is linear: its slope tells whether profit/loss keeps growing without limit
    calls = sum(g["side"] * g["lots"] for g in legs if g["kind"] == "CE")
    puts = sum(g["side"] * g["lots"] for g in legs if g["kind"] == "PE")
    up_unlimited, down_slope = calls > 0, -puts  # P&L slope as price → ∞ is `calls`; as price → 0 it is `-puts`
    max_profit = None if up_unlimited else float(pl.max())
    max_loss = None if calls < 0 else float(pl.min())
    if puts > 0:
        max_profit = None if max_profit is None else max(max_profit, float(payoff(legs, [0.01], lot)[0]))
    del down_slope
    sign = np.sign(pl)
    be = [float(xs[k]) for k in range(len(xs)) if sign[k] == 0]  # grid point exactly at zero P&L
    be += [float(xs[k] - pl[k] * (xs[k + 1] - xs[k]) / (pl[k + 1] - pl[k]))
           for k in range(len(xs) - 1) if sign[k] * sign[k + 1] < 0]  # zero crossed between two points
    be = sorted(be)
    pop = None
    if atm_iv and t > 0:
        sig = atm_iv / 100 * math.sqrt(t)
        z = (np.log(xs / spot) + sig * sig / 2) / sig
        pdf = np.exp(-z * z / 2) / (xs * sig * math.sqrt(2 * math.pi))
        dx = xs[1] - xs[0]
        pop = round(float(((pl > 0) * pdf).sum() * dx / (pdf.sum() * dx)) * 100, 1)
    return {"net_premium": round(net, 2), "max_profit": max_profit and round(max_profit, 0), "max_loss": max_loss and round(max_loss, 0),
            "breakevens": [round(b, 2) for b in be], "pop": pop,
            "reward_risk": round(max_profit / -max_loss, 2) if max_profit and max_loss and max_loss < 0 else None}


def fits(m, iv_rank=None):
    """Which presets suit the current signals. Plain rules, shown as tags, never as a pick."""
    score, mtf = m.get("sig_score") or 0, m.get("mtf_score") or 0
    bull, bear = score >= 2 or mtf >= 2, score <= -2 or mtf <= -2
    event_soon = m.get("days_to_event") is not None and m["days_to_event"] <= (m.get("days_to_expiry") or 99)
    rich = iv_rank is not None and iv_rank >= 60
    cheap = iv_rank is not None and iv_rank <= 30
    out = set()
    if bull:
        out |= {"Long call", "Bull call spread"}
    if bear:
        out |= {"Long put", "Bear put spread"}
    if not bull and not bear:
        out |= {"Iron condor"} | ({"Short straddle"} if rich else set())
    if event_soon or cheap:
        out |= {"Long straddle", "Long strangle"}
    return out


if __name__ == "__main__":
    ch = [{"strike": float(k), "CE": {"ltp": max(100 - k, 0) + 5, "iv": 20}, "PE": {"ltp": max(k - 100, 0) + 5, "iv": 20}}
          for k in range(80, 121, 5)]
    bcs = build("Bull call spread", ch, 100, width=2)          # buy 100 CE @5, sell 110 CE @5 → zero debit
    assert [(g["side"], g["strike"]) for g in bcs] == [(1, 100.0), (-1, 110.0)]
    s = summary(bcs, 100, lot=10, atm_iv=20, t=30 / 365)
    assert s["max_profit"] == 100 and s["max_loss"] == 0 and s["net_premium"] == 0
    st = summary(build("Long straddle", ch, 100), 100, lot=1, atm_iv=20, t=30 / 365)  # pay 10 → breakevens 90 / 110
    assert st["max_profit"] is None and st["max_loss"] == -10 and [round(b) for b in st["breakevens"]] == [90, 110]
    ss = summary(build("Short straddle", ch, 100), 100, lot=1, atm_iv=20, t=30 / 365)
    assert ss["max_loss"] is None and ss["max_profit"] == 10 and 0 < ss["pop"] < 100
    ic = summary(build("Iron condor", ch, 100, width=2), 100, lot=1, atm_iv=20, t=30 / 365)
    assert ic["max_loss"] is not None and ic["max_profit"] is not None  # limited both ways
    assert fits({"sig_score": 3}) >= {"Long call", "Bull call spread"} and "Iron condor" in fits({"sig_score": 0})
    print("ok")
