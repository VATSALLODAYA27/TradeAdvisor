"""Trade setups from the user's own levels, and a checklist for any single option strike. Pure functions.

Nothing here decides for the user: every setup is arithmetic on levels the user's indicators produce (pivots, fib,
supply/demand, option walls, VWAP, EMAs), and every strike check is a pass/fail list against the user's settings.
"""
import math
import re
from datetime import datetime

from option_pick import R, bs_delta, enrich

LEVEL_KEYS = {
    "pivot_s3": "S3", "pivot_s2": "S2", "pivot_s1": "S1", "pivot_p": "Pivot", "pivot_r1": "R1", "pivot_r2": "R2", "pivot_r3": "R3",
    "fib_0": "Fib 0", "fib_05": "Fib 0.5", "fib_1": "Fib 1", "demand_top": "Demand zone", "demand_bottom": "Demand low",
    "supply_bottom": "Supply zone", "supply_top": "Supply high", "fvg_bull_top": "Bullish FVG", "fvg_bear_bottom": "Bearish FVG", "put_wall": "Put wall", "call_wall": "Call wall",
    "max_pain": "Max pain", "vwap": "VWAP", "ema_50": "EMA 50", "ema_200": "EMA 200", "day_high": "Day high", "day_low": "Day low",
    "resistance_20d": "20-day high", "support_20d": "20-day low", "high_52w": "52-week high", "low_52w": "52-week low",
}


# the CE/PE side is only read after a strike number, so symbols ending in CE/PE/C/P (RELIANCE, INFOSYS-P…) stay whole
QUERY = re.compile(r"^\s*([A-Z0-9][A-Z0-9&_-]*?)(?:\s*(\d+(?:\.\d+)?)\s*(CE|PE|CALL|PUT|C|P)?)?\s*$")


def parse_query(text):
    """'NIFTY 22700 PUT' / 'nifty22700pe' / 'RELIANCE 1200 CE' / 'TCS' -> (symbol, strike or None, 'CE'|'PE'|None)."""
    m = QUERY.match((text or "").upper())
    if not m:
        return (text or "").strip().upper(), None, None
    sym, strike, kind = m.groups()
    kind = {"CALL": "CE", "C": "CE", "PUT": "PE", "P": "PE"}.get(kind, kind)
    return sym, float(strike) if strike else None, kind


def _n(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(spot, strike, t, iv_pct, kind):
    """Black-Scholes premium. At expiry (t=0) it is the intrinsic value."""
    if t <= 0 or not iv_pct:
        return max(0.0, spot - strike) if kind == "CE" else max(0.0, strike - spot)
    sig = iv_pct / 100
    d1 = (math.log(spot / strike) + (R + sig * sig / 2) * t) / (sig * math.sqrt(t))
    d2 = d1 - sig * math.sqrt(t)
    if kind == "CE":
        return spot * _n(d1) - strike * math.exp(-R * t) * _n(d2)
    return strike * math.exp(-R * t) * _n(-d2) - spot * _n(-d1)


def years_to(expiry, now=None):
    now = now or datetime.now()  # ponytail: server clock assumed IST, like NSE's 15:30 expiry
    return max((datetime.strptime(expiry, "%d-%b-%Y").replace(hour=15, minute=30) - now).total_seconds(), 0) / (365 * 86400)


VATSAL_PREFIXES = ("pivot_", "fib_", "demand_", "supply_", "fvg_")


def levels(m, vatsal_mode=False):
    """{label: price} of the levels in play, de-duplicated within 0.05%. Pivots, fib and zones are Vatsal-mode only."""
    out = {}
    for k, name in LEVEL_KEYS.items():
        if not vatsal_mode and k.startswith(VATSAL_PREFIXES):
            continue
        v = m.get(k)
        if isinstance(v, (int, float)) and v > 0 and not any(abs(v / p - 1) < 0.0005 for p in out.values()):
            out[name] = float(v)
    return out


def _above(lv, price, gap):
    return sorted([(p, n) for n, p in lv.items() if p >= price + gap])


def _below(lv, price, gap):
    return sorted([(p, n) for n, p in lv.items() if p <= price - gap], reverse=True)


MAX_TARGET_ATR = 3


def underlying_setups(m, atr, vatsal_mode=False):
    """Momentum / pullback / breakout, long and short. Returns dicts with entry, stop, targets and reward:risk."""
    price = m.get("price") or m.get("close")
    lv, gap, buf = levels(m, vatsal_mode), 0.3 * atr, 0.1 * atr
    out = []
    for side in ("LONG", "SHORT"):
        up = side == "LONG"
        ahead = (_above if up else _below)          # targets lie ahead, stops behind
        behind = (_below if up else _above)
        sgn = 1 if up else -1

        def make(kind, entry, entry_why, stop_from):
            stops = behind(lv, entry, gap) if stop_from is None else [stop_from]
            # targets must be reachable: a level further than MAX_TARGET_ATR × ATR away is not a realistic first target
            tgts = [(p, n) for p, n in ahead(lv, entry, gap) if abs(p - entry) <= MAX_TARGET_ATR * atr]
            # no level on that side: fall back to ATR distances, labelled as such
            stops = stops or [(entry - sgn * (atr - buf), "1×ATR")]
            tgts = tgts or [(entry + sgn * 1.5 * atr, "1.5×ATR"), (entry + sgn * 2.5 * atr, "2.5×ATR")]
            stop_lv, stop_name = stops[0]
            stop = stop_lv - sgn * buf
            t1, t1n = tgts[0]
            t2, t2n = tgts[1] if len(tgts) > 1 else (None, None)
            risk = (entry - stop) * sgn
            if risk <= 0:
                return None
            return {"side": side, "kind": kind, "entry": round(entry, 2), "entry_why": entry_why,
                    "stop": round(stop, 2), "stop_why": f"beyond {stop_name} {stop_lv:,.2f}",
                    "t1": round(t1, 2), "t1_why": t1n, "t2": t2 and round(t2, 2), "t2_why": t2n,
                    "rr": round((t1 - entry) * sgn / risk, 2), "risk_pct": round(risk / entry * 100, 2)}

        out.append(make("Momentum", price, "market price now", None))
        near = behind(lv, price, 0.1 * atr)          # pullback into the nearest level behind price
        if near and abs(near[0][0] - price) <= 1.5 * atr:
            p, n = near[0]
            nxt = behind(lv, p, gap)
            out.append(make("Pullback", p, f"at {n}", nxt[0] if nxt else None))
        brk = ahead(lv, price, 0.1 * atr)            # breakout through the nearest level ahead
        if brk:
            p, n = brk[0]
            out.append(make("Breakout", p + sgn * buf, f"close beyond {n} {p:,.2f}", (p - sgn * 0.5 * atr, f"{n} retest")))
    return [s for s in out if s]


def setup_verdict(setup, bias):
    """BUY (long) / SELL (short), or AVOID when the reward doesn't pay for the risk. Returns (label, reason)."""
    rr, counter = setup["rr"], bool(bias) and bias != (1 if setup["side"] == "LONG" else -1)
    if rr < 1:
        return "AVOID", f"reward:risk {rr} is below 1"
    if counter and rr < 1.5:
        return "AVOID", f"counter-trend and reward:risk {rr} is below 1.5"
    return ("BUY" if setup["side"] == "LONG" else "SELL"), (f"reward:risk {rr}" + (", counter-trend" if counter else ", with the trend"))


def strike_verdict(checks):
    """BUY / SELL / AVOID for one option from its checklist.
    AVOID if illiquid; BUY if liquid, breakeven reachable, IV not rich and >= 2/3 of direction checks agree;
    SELL (write it, or exit if held) if liquid and <= 1/3 agree; otherwise AVOID (mixed)."""
    by = {c["name"]: c["pass"] for c in checks}
    liquid = by["Liquid: OI ≥ your minimum"] and by["Tight spread ≤ your maximum"]
    direction = [c["pass"] for c in checks if c.get("direction")]
    share = sum(direction) / len(direction) if direction else 0
    if not liquid:
        return "AVOID", "fails your liquidity / spread filters"
    if share >= 2 / 3 and by["Breakeven inside the expected move"] and by["IV not rich vs ATM (≤ 1.2×)"]:
        return "BUY", f"{sum(direction)}/{len(direction)} direction checks agree, breakeven reachable, IV fair"
    if share <= 1 / 3:
        return "SELL", f"only {sum(direction)}/{len(direction)} direction checks agree: the move favours the other side"
    return "AVOID", f"mixed: {sum(direction)}/{len(direction)} direction checks agree"


def option_legs(setup, chain, spot, expiry, cfg, deltas=(0.35, 0.5, 0.65), now=None):
    """For a setup, the liquid CE (long) / PE (short) strikes nearest each target delta, with premiums re-priced
    at the setup's entry, stop and target (Black-Scholes on the strike's own IV, same expiry time)."""
    kind = "CE" if setup["side"] == "LONG" else "PE"
    t = years_to(expiry, now)
    legs = [x for x in (enrich(r, kind, spot, t) for r in chain) if x and x["delta"] is not None
            and x["oi"] >= cfg["min_oi"] and x["spread_pct"] <= cfg["max_spread_pct"]]
    if not legs:
        return []
    otm_d, atm_d, itm_d = deltas
    atm = min(legs, key=lambda l: abs(abs(l["delta"]) - atm_d))
    # OTM / ITM are searched only on their own side of the ATM strike, so the three never collapse into one
    otm = [l for l in legs if abs(l["delta"]) < abs(atm["delta"])]
    itm = [l for l in legs if abs(l["delta"]) > abs(atm["delta"])]
    picks = [("OTM", otm and min(otm, key=lambda l: abs(abs(l["delta"]) - otm_d))), ("ATM", atm),
             ("ITM", itm and min(itm, key=lambda l: abs(abs(l["delta"]) - itm_d)))]
    out = []
    for label, x in picks:
        if not x:
            continue
        at = lambda s: round(bs_price(s, x["strike"], t, x["iv"], kind), 2)
        # anchor to the market: model error at spot is carried as an offset to the other levels
        off = x["ltp"] - at(spot)
        e, s, t1 = (max(0.05, at(p) + off) for p in (setup["entry"], setup["stop"], setup["t1"]))
        risk = e - s
        out.append({"label": label, "kind": kind, "strike": x["strike"], "ltp": x["ltp"], "delta": x["delta"], "iv": x["iv"],
                    "prem_entry": round(e, 2), "prem_stop": round(s, 2), "prem_t1": round(t1, 2),
                    "rr": round((t1 - e) / risk, 2) if risk > 0 else None})
    return out


def check_strike(chain, spot, expiry, strike, kind, m, verdicts, cfg, now=None, vatsal_mode=False):
    """Everything measurable about one option, as facts plus a pass/fail checklist against the user's own settings."""
    row = next((r for r in chain if r["strike"] == strike), None)
    t = years_to(expiry, now)
    x = row and enrich(row, kind, spot, t)
    if not x:
        near = sorted(chain, key=lambda r: abs(r["strike"] - strike))[:5]
        return {"error": f"No two-sided quote for {strike:g} {kind} in the {expiry} chain. "
                         f"Nearby strikes: {', '.join(f'{r['strike']:g}' for r in sorted(near, key=lambda r: r['strike']))}"}
    atm = min(chain, key=lambda r: abs(r["strike"] - spot))
    atm_legs = [enrich(atm, k, spot, t) for k in ("CE", "PE")]
    atm_iv = sum(l["iv"] for l in atm_legs if l) / max(1, sum(1 for l in atm_legs if l))
    sgn = 1 if kind == "CE" else -1
    dist = (strike - spot) / spot * 100 * sgn  # >0 = OTM
    money = "ATM" if abs(dist) < 0.5 else ("OTM" if dist > 0 else "ITM")
    exp_move = spot * atm_iv / 100 * math.sqrt(t) if t > 0 else 0
    need = abs(x["breakeven"] - spot) if (x["breakeven"] - spot) * sgn > 0 else 0

    def prob_beyond(level):  # risk-neutral P(spot at expiry beyond level in the option's direction)
        if t <= 0 or not x["iv"]:
            return None
        sig = x["iv"] / 100
        d2 = (math.log(spot / level) + (R - sig * sig / 2) * t) / (sig * math.sqrt(t))
        return round(_n(d2 * sgn) * 100, 1)

    theta = round(bs_price(spot, strike, max(t - 1 / 365, 0), x["iv"], kind) - bs_price(spot, strike, t, x["iv"], kind), 2)
    pc, oc = row[kind].get("chg", 0), x["chg_oi"]
    buildup = ("Long build-up" if pc > 0 and oc > 0 else "Short build-up" if pc < 0 and oc > 0 else
               "Short covering" if pc > 0 and oc < 0 else "Long unwinding" if pc < 0 and oc < 0 else "No clear build-up")
    lv = levels(m, vatsal_mode)
    tgt = (_above if kind == "CE" else _below)(lv, spot, 0)
    stp = (_below if kind == "CE" else _above)(lv, spot, 0)
    at = lambda s: round(max(0.05, bs_price(s, strike, t, x["iv"], kind) + x["ltp"] - bs_price(spot, strike, t, x["iv"], kind)), 2)

    agree = lambda v: v in (cfg["ce_on"] if kind == "CE" else cfg["pe_on"])
    side_bias = sgn
    checks = [  # the 4th field marks the direction checks used by strike_verdict
        ("Liquid: OI ≥ your minimum", x["oi"] >= cfg["min_oi"], f"OI {x['oi']:,} vs min {cfg['min_oi']:,}"),
        ("Tight spread ≤ your maximum", x["spread_pct"] <= cfg["max_spread_pct"], f"{x['spread_pct']}% vs max {cfg['max_spread_pct']}%"),
        ("Breakeven inside the expected move", need <= exp_move, f"needs {need:,.1f} pts, 1-σ move to expiry ≈ {exp_move:,.1f}"),
        ("IV not rich vs ATM (≤ 1.2×)", x["iv"] <= 1.2 * atm_iv, f"IV {x['iv']}% vs ATM {atm_iv:.1f}%"),
        *([("Daily Vatsal bias agrees", m.get("vs_bias") == side_bias, f"vs_bias {m.get('vs_bias')}", True),
           ("5-min Vatsal bias agrees", m.get("vs5m_bias") == side_bias, f"vs5m_bias {m.get('vs5m_bias')}", True)]
          if vatsal_mode else [("Trend agrees (price vs EMA 200)", (m.get("close", 0) - m.get("ema_200", 0)) * side_bias > 0,
                                f"close {m.get('close')} vs EMA 200 {m.get('ema_200')}", True)]),
        (f"{cfg['advisor']} advisor points this way", agree((verdicts.get(cfg["advisor"]) or {}).get("verdict")),
         f"{cfg['advisor']} says {(verdicts.get(cfg['advisor']) or {}).get('verdict', 'not run')}", True),
        ("Option OI is building with price (long build-up)", buildup == "Long build-up", buildup, True),
        ("Timeframes agree (15m / 1h / daily)", (m.get("mtf_score") or 0) * side_bias >= 2,
         f"mtf_score {m.get('mtf_score')} (+3 all bullish, −3 all bearish)", True),
        ("No results / board meeting before expiry", m.get("days_to_event") is None
         or m["days_to_event"] > (m.get("days_to_expiry") or 0),
         m.get("event") or "no event scheduled"),
    ]
    checks = [{"name": c[0], "pass": bool(c[1]), "detail": c[2], "direction": len(c) > 3} for c in checks]
    verdict, why = strike_verdict(checks)
    return {
        "kind": kind, "strike": strike, "expiry": expiry, "spot": spot, "leg": x, "moneyness": money, "distance_pct": round(dist, 2),
        "atm_iv": round(atm_iv, 2), "expected_move": round(exp_move, 1), "breakeven_need": round(need, 1),
        "prob_itm": prob_beyond(strike), "prob_breakeven": prob_beyond(x["breakeven"]), "theta_day": theta, "buildup": buildup,
        "target": tgt[0] if tgt else None, "prem_at_target": tgt and at(tgt[0][0]),
        "stop": stp[0] if stp else None, "prem_at_stop": stp and at(stp[0][0]),
        "checks": checks, "verdict": verdict, "verdict_why": why,
    }
