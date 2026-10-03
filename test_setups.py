"""Offline checks for vatsal.py and setups.py on synthetic data."""
import math
from datetime import datetime

import numpy as np
import pandas as pd

import vatsal
from setups import bs_price, check_strike, option_legs, underlying_setups

# --- Black-Scholes: put-call parity, and intrinsic value at expiry ---
S, K, t, iv, r = 100, 105, 30 / 365, 25, 0.065
assert abs((bs_price(S, K, t, iv, "CE") - bs_price(S, K, t, iv, "PE")) - (S - K * math.exp(-r * t))) < 1e-9
assert bs_price(110, 100, 0, 20, "CE") == 10 and bs_price(90, 100, 0, 20, "PE") == 10

# --- pivots match the textbook formula ---
p = vatsal.pivots(110, 90, 100)
assert p["P"] == 100 and p["R1"] == 110 and p["S1"] == 90 and p["R2"] == 120 and p["S3"] == 70

# --- signals: a clean uptrend fires exactly one BUY once the 5/13 trigger crosses up while price > EMA200 and 50 > 200 ---
n = 400
close = np.concatenate([np.linspace(100, 200, 300), np.linspace(200, 190, 40), np.linspace(190, 230, 60)])
d = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000.0},
                 index=pd.date_range("2024-01-01", periods=n, freq="D"))
sig = vatsal.signals(d, vatsal.DEFAULTS)
assert sig["bias"].iloc[-1] == 1
assert (sig["signal"] == -1).sum() == 0          # never a SELL while price stays above EMA200 with 50 > 200
assert vatsal.last_signal(sig["signal"])[0] == 1  # the dip-and-recover re-crosses 5/13 upward -> BUY
assert (sig["signal"].diff().fillna(0) != 0).sum() >= 1

# --- zigzag / fib: a single up-swing gives fib 0 at the high and 1 at the low ---
wave = np.concatenate([np.linspace(100, 150, 60), np.linspace(150, 110, 60), np.linspace(110, 170, 60), np.linspace(170, 160, 20)])
w = pd.DataFrame({"Open": wave, "High": wave + .5, "Low": wave - .5, "Close": wave, "Volume": 1.0},
                 index=pd.date_range("2024-01-01", periods=len(wave), freq="D"))
f = vatsal.fib(w, vatsal.DEFAULTS)
assert f and f["direction"] == "up" and abs(f["levels"][0] - 170.5) < 1e-6 and abs(f["levels"][1] - 109.5) < 1e-6

# --- fair value gaps: a gap-up leaves a bullish FVG until price trades back into it ---
bars = [(100, 101, 99, 100), (100, 106, 100, 105), (107, 110, 107, 109), (109, 111, 108, 110)]  # low 107 > high 101
g = pd.DataFrame(bars, columns=["Open", "High", "Low", "Close"]).assign(Volume=1.0)
fv = vatsal.fair_value_gaps(g, vatsal.DEFAULTS)
assert fv == [{"kind": "fvg_bull", "start": 1, "top": 107.0, "bottom": 101.0},   # low 107 > high 101
              {"kind": "fvg_bull", "start": 2, "top": 108.0, "bottom": 106.0}]   # low 108 > high 106
assert vatsal.fair_value_gaps(pd.concat([g, pd.DataFrame([(108, 108, 100.5, 101)], columns=["Open", "High", "Low", "Close"]).assign(Volume=1.0)],
                                        ignore_index=True), vatsal.DEFAULTS) == []  # filled
assert vatsal.fair_value_gaps(g, vatsal.DEFAULTS | {"fvg": False}) == []

# --- setups: levels on both sides give long and short trades with stops behind entry and targets ahead ---
m = {"price": 100.0, "pivot_s1": 95.0, "pivot_s2": 90.0, "pivot_r1": 105.0, "pivot_r2": 110.0, "vwap": 99.0}
std_setups = underlying_setups(m | {"day_high": 103.0}, atr=4)  # standard view never uses Vatsal's pivots
assert std_setups and not any(k in x[f] for x in std_setups for f in ("stop_why", "t1_why", "entry_why") for k in ("S1", "S2", "R1", "R2"))
ss = underlying_setups(m, atr=4, vatsal_mode=True)
assert {s["side"] for s in ss} == {"LONG", "SHORT"}
for s in ss:
    ahead = 1 if s["side"] == "LONG" else -1
    assert (s["t1"] - s["entry"]) * ahead > 0 and (s["entry"] - s["stop"]) * ahead > 0, s
mom = next(s for s in ss if s["side"] == "LONG" and s["kind"] == "Momentum")
assert mom["t1"] == 105.0 and mom["stop"] == 95.0 - 0.4 and mom["rr"] == round(5 / 5.4, 2)


# --- option legs and strike check ---
def leg(ltp, iv=20, oi=1000):
    return {"ltp": ltp, "bid": ltp - .05, "ask": ltp + .05, "iv": iv, "oi": oi, "chg_oi": 50, "volume": 10, "chg": 1}


now = datetime(2026, 9, 29, 10, 0)
T = (datetime(2026, 10, 27, 15, 30) - now).total_seconds() / (365 * 86400)
chain = [{"strike": float(k), "CE": leg(round(bs_price(100, k, T, 20, "CE"), 2)), "PE": leg(round(bs_price(100, k, T, 20, "PE"), 2))}
         for k in range(90, 111, 5)]
cfg = {"advisor": "options", "ce_on": ["BULLISH"], "pe_on": ["BEARISH"], "target_delta": 0.5, "min_oi": 100, "max_spread_pct": 10}
legs = option_legs(mom, chain, 100.0, "27-Oct-2026", cfg, now=now)
assert legs and all(l["kind"] == "CE" and l["prem_stop"] < l["prem_entry"] < l["prem_t1"] for l in legs)
assert abs(legs[[l["label"] for l in legs].index("ATM")]["prem_entry"] - chain[2]["CE"]["ltp"]) < 0.02  # entry at spot = market

res = check_strike(chain, 100.0, "27-Oct-2026", 100.0, "CE", m | {"vs_bias": 1, "vs5m_bias": -1},
                   {"options": {"verdict": "BULLISH"}}, cfg, now=now, vatsal_mode=True)
checks = {c["name"]: c["pass"] for c in res["checks"]}
assert res["moneyness"] == "ATM" and checks["Daily Vatsal bias agrees"] and not checks["5-min Vatsal bias agrees"]
assert checks["options advisor points this way"] and checks["Option OI is building with price (long build-up)"]
assert 40 < res["prob_itm"] < 60 and res["theta_day"] < 0
assert "error" in check_strike(chain, 100.0, "27-Oct-2026", 123.0, "CE", m, {}, cfg, now=now)
std = {c["name"] for c in check_strike(chain, 100.0, "27-Oct-2026", 100.0, "CE", m, {}, cfg, now=now)["checks"]}
assert "Trend agrees (price vs EMA 200)" in std and not any("Vatsal" in n for n in std)
bare = underlying_setups({"price": 100.0}, atr=4)  # no levels at all: ATR fallbacks, both sides
assert {(x["side"], x["kind"]) for x in bare} == {("LONG", "Momentum"), ("SHORT", "Momentum")}
assert all(x["t1_why"] == "1.5×ATR" and x["stop_why"].startswith("beyond 1×ATR") and x["rr"] == 1.5 for x in bare)
from setups import parse_query, setup_verdict, strike_verdict
assert parse_query("nifty 22700 put") == ("NIFTY", 22700.0, "PE")
assert parse_query("NIFTY22700CE") == ("NIFTY", 22700.0, "CE")
assert parse_query("NIFTY 50") == ("NIFTY", None, None) and parse_query("nifty 50 22700 pe") == ("NIFTY", 22700.0, "PE")  # index name, not strike 50
assert parse_query(" reliance 1200 c ") == ("RELIANCE", 1200.0, "CE")
assert parse_query("BANKNIFTY 51000") == ("BANKNIFTY", 51000.0, None)
assert parse_query("TCS") == ("TCS", None, None) and parse_query("M&M") == ("M&M", None, None)
assert parse_query("BAJAJ-AUTO 9000 PE") == ("BAJAJ-AUTO", 9000.0, "PE")
for plain in ("RELIANCE", "ULTRACEMCO", "BHARTIARTL", "HINDALCO", "SBIN", "360ONE", "NIFTY", "APOLLOHOSP", "TECHM"):
    assert parse_query(plain) == (plain, None, None), (plain, parse_query(plain))
assert parse_query("reliance 1200 ce") == ("RELIANCE", 1200.0, "CE") and parse_query("360ONE 1100 PE") == ("360ONE", 1100.0, "PE")
assert setup_verdict({"side": "LONG", "rr": 2.0}, 1) == ("BUY", "reward:risk 2.0, with the trend")
assert setup_verdict({"side": "SHORT", "rr": 1.2}, 1)[0] == "AVOID"   # counter-trend needs 1.5
assert setup_verdict({"side": "SHORT", "rr": 1.6}, 1)[0] == "SELL"
assert setup_verdict({"side": "LONG", "rr": 0.8}, 1)[0] == "AVOID"
assert res["verdict"] in ("BUY", "SELL", "AVOID") and res["verdict_why"]
base = [{"name": "Liquid: OI ≥ your minimum", "pass": True}, {"name": "Tight spread ≤ your maximum", "pass": True},
        {"name": "Breakeven inside the expected move", "pass": True}, {"name": "IV not rich vs ATM (≤ 1.2×)", "pass": True}]
dirs = lambda *ok: [{"name": f"d{i}", "pass": v, "direction": True} for i, v in enumerate(ok)]
assert strike_verdict(base + dirs(True, True, False))[0] == "BUY"
assert strike_verdict(base + dirs(True, False, False))[0] == "SELL"
assert strike_verdict(base + dirs(True, True, False, False))[0] == "AVOID"
assert strike_verdict([{**base[0], "pass": False}] + base[1:] + dirs(True, True, True))[0] == "AVOID"
far = underlying_setups({"price": 100.0, "low_52w": 40.0, "pivot_r1": 104.0}, atr=4, vatsal_mode=True)
assert all(abs(x["t1"] - x["entry"]) <= 3 * 4 + 1e-9 for x in far)  # the 52-week low 60% away is never a target
print("ok")
