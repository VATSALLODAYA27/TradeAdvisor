from datetime import datetime

from option_pick import bs_delta, pick

# delta sanity: ATM ~0.5, deep ITM call ~1, put = call - 1
t = 7 / 365
assert 0.48 < bs_delta(100, 100, t, 20, "CE") < 0.53
assert bs_delta(100, 70, t, 20, "CE") > 0.99
assert abs(bs_delta(100, 105, t, 20, "PE") - (bs_delta(100, 105, t, 20, "CE") - 1)) < 1e-12
assert bs_delta(100, 100, t, 0, "CE") is None  # no IV -> no delta


def leg(ltp, oi=1000, spread=0.05, iv=20):
    return {"ltp": ltp, "bid": ltp - spread / 2, "ask": ltp + spread / 2, "iv": iv, "oi": oi, "chg_oi": 0, "volume": 10}


chain = [
    {"strike": 90.0, "CE": leg(10.5), "PE": leg(0.3)},
    {"strike": 95.0, "CE": leg(6.0), "PE": leg(1.0)},
    {"strike": 100.0, "CE": leg(3.0, oi=5), "PE": leg(3.0)},      # ATM call: too little OI
    {"strike": 105.0, "CE": leg(1.0), "PE": leg(6.0, spread=3)},  # PE spread 50% -> filtered out
    {"strike": 110.0, "CE": leg(0.3), "PE": leg(10.2)},
]
cfg = {"advisor": "options", "ce_on": ["BULLISH"], "pe_on": ["BEARISH"], "target_delta": 0.5, "min_oi": 100, "max_spread_pct": 10}
now = datetime(2026, 9, 29, 10, 0)

p = pick(chain, 100.4, "06-Oct-2026", "BULLISH", cfg, now)
assert p["signal"] == "CE" and p["atm"] == 100.0
liquid_ce = [r["CE"] for r in p["chain"] if r["CE"]["oi"] >= 100]
assert p["CE"]["strike"] != 100.0  # ATM call is illiquid
assert p["CE"] == min(liquid_ce, key=lambda x: abs(x["delta"] - 0.5))  # closest liquid delta wins
assert p["PE"]["strike"] == 100.0
assert p["CE"]["breakeven"] == p["CE"]["strike"] + p["CE"]["ltp"]
assert p["PE"]["breakeven"] == 97.0  # 100 PE @ 3
assert pick(chain, 100.4, "06-Oct-2026", "BEARISH", cfg, now)["signal"] == "PE"
assert pick(chain, 100.4, "06-Oct-2026", "NEUTRAL", cfg, now)["signal"] is None
assert pick(chain, 100.4, "06-Oct-2026", "BULLISH", {**cfg, "min_oi": 10**6}, now)["CE"] is None  # nothing liquid
print("ok")
