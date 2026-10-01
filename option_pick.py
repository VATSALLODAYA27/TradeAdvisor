"""Pick the strike to BUY on the CE or PE side. Pure functions; the chain comes from data.option_metrics().

Side   : your options advisor's verdict (settings: option_pick.ce_on / pe_on labels).
Strike : among liquid strikes (min OI, max bid/ask spread), the one whose |delta| is closest to target_delta.
"""
import math
from datetime import datetime

R = 0.065  # ponytail: fixed risk-free rate (~Indian T-bill yield); moves delta <0.01 on weekly/monthly expiries
WINDOW = 8  # strikes each side of ATM in the returned mini chain


def bs_delta(spot, strike, t_years, iv_pct, kind):
    """Black-Scholes delta from NSE's implied volatility. None when IV or time is missing."""
    if not iv_pct or t_years <= 0 or spot <= 0 or strike <= 0:
        return None
    sig = iv_pct / 100
    d1 = (math.log(spot / strike) + (R + sig * sig / 2) * t_years) / (sig * math.sqrt(t_years))
    n = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return n if kind == "CE" else n - 1


def enrich(row, kind, spot, t):
    """Chain leg -> display dict with spread, delta and breakeven. None if the leg has no two-sided quote."""
    o = row.get(kind)
    if not o or not o["ltp"] or not o["bid"] or not o["ask"]:
        return None
    k, ltp = row["strike"], o["ltp"]
    be = k + ltp if kind == "CE" else k - ltp
    delta = bs_delta(spot, k, t, o["iv"], kind)
    return {
        "kind": kind, "strike": k, **o,
        "spread_pct": round((o["ask"] - o["bid"]) / ((o["ask"] + o["bid"]) / 2) * 100, 2),
        "delta": None if delta is None else round(delta, 3),
        "breakeven": round(be, 2),
        "breakeven_move_pct": round((be / spot - 1) * 100, 2),  # how far spot must move by expiry to break even
    }


def best(chain, kind, spot, t, cfg):
    legs = [enrich(r, kind, spot, t) for r in chain]
    ok = [x for x in legs if x and x["delta"] is not None
          and x["oi"] >= cfg["min_oi"] and x["spread_pct"] <= cfg["max_spread_pct"]]
    return min(ok, key=lambda x: abs(abs(x["delta"]) - cfg["target_delta"])) if ok else None


def pick(chain, spot, expiry, verdict, cfg, now=None):
    """chain: [{strike, CE: {ltp,bid,ask,iv,oi,chg_oi,volume}, PE: {...}}], expiry 'DD-Mon-YYYY' (expires 15:30 IST)."""
    now = now or datetime.now()  # ponytail: assumes the server clock is IST, like the NSE expiry times
    t = max((datetime.strptime(expiry, "%d-%b-%Y").replace(hour=15, minute=30) - now).total_seconds(), 0) / (365 * 86400)
    side = "CE" if verdict in cfg["ce_on"] else "PE" if verdict in cfg["pe_on"] else None
    chain = sorted(chain, key=lambda r: r["strike"])
    atm = min(range(len(chain)), key=lambda i: abs(chain[i]["strike"] - spot))
    window = chain[max(0, atm - WINDOW): atm + WINDOW + 1]
    return {
        "advisor": cfg["advisor"],
        "verdict": verdict,
        "signal": side,
        "expiry": expiry,
        "spot": spot,
        "target_delta": cfg["target_delta"],
        "CE": best(chain, "CE", spot, t, cfg),
        "PE": best(chain, "PE", spot, t, cfg),
        "atm": chain[atm]["strike"],
        "chain": [{"strike": r["strike"], "CE": enrich(r, "CE", spot, t), "PE": enrich(r, "PE", spot, t)} for r in window],
    }
