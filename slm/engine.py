"""The Python quant engine. Computes every number the model may quote (PRD §2 and §4 'zero arithmetic hallucination')."""
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import indicators as ind

DRIFT = 5.0  # ± % drift tolerance (PRD 2a)
SLEEVES = [  # sleeve, target %, default fund (Direct Plan, Growth), asset proxy key (sources.ASSETS)
    ("International Equity", 35, "Motilal Oswal Nasdaq 100 FOF - Direct Growth", "International Equity"),
    ("Gold", 25, "Nippon India Gold Savings Fund - Direct Growth", "Gold"),
    ("Bonds / Fixed Income", 25, "HDFC Short Term Debt Fund - Direct Growth", "Bonds"),
    ("Indian Equity", 15, "UTI Nifty 50 Index Fund - Direct Growth", "Indian Equity"),
]
POSITIONS = 10  # equal-weight positions per stock sleeve (PRD 2b)


# ---------- regime, features, breadth ----------

def regime(d):
    """Nifty 500 Supertrend (10, 3) on weekly and daily candles. Weekly decides bull / bear for every rule."""
    return {"nifty500_close": round(float(d["Close"].iloc[-1]), 2),
            "nifty500_supertrend_weekly": int(ind.supertrend(ind.weekly(d)).iloc[-1]),
            "nifty500_supertrend_daily": int(ind.supertrend(d).iloc[-1])}


def features(d):
    """Every screen input for one stock. None when there are fewer than 220 sessions (SMA 200 must be real)."""
    if len(d) < 220:
        return None
    c, w = d["Close"], ind.weekly(d)
    last, sma50, sma200 = float(c.iloc[-1]), float(ind.sma(c, 50).iloc[-1]), float(ind.sma(c, 200).iloc[-1])
    vol20 = float(d["Volume"].iloc[-21:-1].mean())
    return {
        "close": round(last, 2), "ret_6m": float(last / c.iloc[-127] - 1), "ret_1d_pct": round(float(last / c.iloc[-2] - 1) * 100, 2),
        "sma50": sma50, "sma200": sma200, "above_sma50": last > sma50, "above_sma200": last > sma200,
        "rsi_d": round(float(ind.rsi(c).iloc[-1]), 1), "rsi_w": round(float(ind.rsi(w["Close"]).iloc[-1]), 1),
        "st_d": int(ind.supertrend(d).iloc[-1]), "st_w": int(ind.supertrend(w).iloc[-1]),
        "pct_from_ema10w": round((last / float(ind.ema(w["Close"], 10).iloc[-1]) - 1) * 100, 2),
        "pct_from_ema9": round((last / float(ind.ema(c, 9).iloc[-1]) - 1) * 100, 2),
        "pct_from_52w_high": round((last / float(d["High"].tail(252).max()) - 1) * 100, 2),
        "volume_vs_20d": round(float(d["Volume"].iloc[-1]) / vol20, 2) if vol20 else None,
    }


def breadth(feats):
    n = len(feats)
    pct = lambda k: round(sum(1 for f in feats.values() if f[k]) / n * 100, 1)
    return {"stocks_measured": n, "pct_above_sma50": pct("above_sma50"), "pct_above_sma200": pct("above_sma200")} if n else {}


def rs_and_sector(feats, industry):
    """RS percentile (6-month return rank across the universe) and each stock's 6-month return minus its industry median."""
    ret = pd.Series({t: f["ret_6m"] for t, f in feats.items()})
    rs = ret.rank(pct=True) * 100
    sec = pd.Series({t: industry.get(t) for t in ret.index})
    med = ret.groupby(sec).median()
    return ({t: round(float(rs[t]), 1) for t in ret.index},
            {t: round(float(ret[t] - med[sec[t]]) * 100, 2) if sec[t] in med else None for t in ret.index})


# ---------- the two stock models ----------

def next_monday(today=None):
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def screens(feats, rs, sector_rel, industry, bull, today=None):
    """Weekly Core Defense and Daily Tactical & Hedged signals (PRD 2b), best 10 by RS each."""
    core, tact = [], []
    monday = next_monday(today).isoformat()
    for t, f in feats.items():
        base = {"ticker": t, "industry": industry.get(t), "entry_price": f["close"], "rs_percentile": rs[t],
                "sector_relative_6m_pct": sector_rel[t], "pct_from_52w_high": f["pct_from_52w_high"], "volume_vs_20d": f["volume_vs_20d"]}
        if 90 <= rs[t] <= 98 and f["rsi_w"] > 60 and f["st_w"] == 1 and abs(f["pct_from_ema10w"]) <= 7:
            core.append(base | {"stop_loss_price": round(f["close"] * 0.90, 2), "stop_rule": "-10% strict", "execution": f"Monday open {monday}",
                                "weekly_rsi14": f["rsi_w"], "weekly_supertrend": f["st_w"], "pct_from_10w_ema": f["pct_from_ema10w"]})
        # shortcut: the PRD's "EMA 9 pullback band" has no width; read as close 0-2% above EMA 9. Widen here if it's too strict.
        if (f["sma50"] > f["sma200"] and f["above_sma200"] and f["st_d"] == 1 and f["rsi_d"] >= 55 and f["ret_1d_pct"] > -0.5
                and 0 <= f["pct_from_ema9"] <= 2):
            tact.append(base | {"stop_loss_price": round(f["close"] * (0.70 if bull else 0.90), 2),
                                "stop_rule": "-30% (bull regime)" if bull else "-10% (bear regime)", "execution": "next session open",
                                "daily_rsi14": f["rsi_d"], "daily_supertrend": f["st_d"], "pct_from_ema9": f["pct_from_ema9"],
                                "return_1d_pct": f["ret_1d_pct"]})
    best = lambda xs: sorted(xs, key=lambda x: -x["rs_percentile"])[:POSITIONS]
    return best(core), best(tact)


def size(signals, capital):
    """Equal weight: capital / 10 per position, whole shares. Adds position_inr, quantity and weight_pct."""
    per = capital / POSITIONS if capital else None
    for s in signals:
        s["weight_pct"] = round(100 / POSITIONS, 2)
        s["position_inr"] = round(per, 2) if per else None
        s["quantity"] = math.floor(per / s["entry_price"]) if per else None
    return signals


def delivery_spikes(signals, deliv):
    """Institutional footprint: today's delivery % vs its average over the previous sessions in the bhavcopy window."""
    for s in signals:
        col = deliv.get(s["ticker"]) if deliv is not None and not deliv.empty else None
        if col is None or col.dropna().size < 3:
            s |= {"delivery_pct": None, "delivery_avg_pct": None, "delivery_spike": None}
            continue
        col = col.dropna()
        now, avg = float(col.iloc[-1]), float(col.iloc[:-1].mean())
        s |= {"delivery_pct": round(now, 2), "delivery_avg_pct": round(avg, 2), "delivery_spike": bool(avg and now >= 1.5 * avg)}
    return signals


# ---------- mutual funds, hedge, exits ----------

def mf_allocation(funds, holdings, review_due):
    """Target vs current per sleeve; the engine decides the action and the rupee amount (PRD 2a, rule 5)."""
    hold = {s: float(holdings.get(s) or 0) for s, *_ in SLEEVES}
    total = sum(hold.values())
    rows = []
    for s, tgt, default, _ in SLEEVES:
        cur = hold[s] / total * 100 if total else None
        rows.append({"sleeve": s, "fund_name": funds.get(s) or default, "target_pct": tgt, "current_inr": round(hold[s], 2),
                     "current_pct": None if cur is None else round(cur, 2), "drift_pct": None if cur is None else round(cur - tgt, 2),
                     "target_inr": round(total * tgt / 100, 2) if total else None})
    due_drift = any(r["drift_pct"] is not None and abs(r["drift_pct"]) > DRIFT for r in rows)
    for r in rows:
        gap = None if r["target_inr"] is None else round(r["target_inr"] - r["current_inr"], 2)
        act = ("BUY" if gap > 0 else "SELL") if (due_drift or review_due) and gap else "HOLD"
        r |= {"rebalance_action": act, "amount_inr": abs(gap) if act != "HOLD" else None}
    return {"total_inr": round(total, 2), "drift_tolerance_pct": DRIFT, "rebalance_due_by_drift": due_drift,
            "annual_review_flagged": review_due, "funds": rows}


def hedge(bull, cash, prices):
    """Dynamic downside hedge: in a bear regime, unallocated cash splits 50/50 into GOLDBEES.NS and SILVERBEES.NS."""
    if bull:
        return {"active": False, "note": "Inactive: Nifty 500 weekly Supertrend is 1", "orders": []}
    orders = []
    for etf in ("GOLDBEES.NS", "SILVERBEES.NS"):
        px = prices.get(etf)
        amt = round(cash / 2, 2) if cash else None
        orders.append({"etf": etf, "price": px, "amount_inr": amt, "units": math.floor(amt / px) if amt and px else None})
    return {"active": True, "note": "Bear regime: stock buying frozen; unallocated cash moves into gold and silver ETFs",
            "unallocated_cash_inr": cash, "orders": orders}


def exits(positions, feats, bull):
    """Exit triggers for the desk's own stock positions (entered on the tab), by the rules of the sleeve they came from."""
    out = []
    for p in positions:
        t, f, entry = p["ticker"], feats.get(p["ticker"]), p.get("entry_price")
        if not f or not entry:
            continue
        pl = round((f["close"] / entry - 1) * 100, 2)
        why = []
        if p.get("sleeve") == "Weekly Core":
            why += [f"Strict stop: {pl}% from entry {entry} (limit -10%)"] if pl <= -10 else []
            why += ["Weekly Supertrend flipped to -1"] if f["st_w"] == -1 else []
        else:
            lim = -30 if bull else -10
            why += [f"Dynamic stop: {pl}% from entry {entry} (limit {lim}% in a {'bull' if bull else 'bear'} regime)"] if pl <= lim else []
            why += ["Daily Supertrend flipped to -1"] if f["st_d"] == -1 else []
            why += ["Close below the 200-day SMA"] if not f["above_sma200"] else []
        if why:
            out.append({"ticker": t, "strategy_sleeve": p.get("sleeve"), "entry_price": entry, "close": f["close"], "pnl_pct": pl,
                        "exit_trigger": "; ".join(why)})
    return out


# ---------- macro ----------

def asset_trends(closes):
    """Trend momentum per asset class: 3- and 12-month return and position vs the 200-day SMA."""
    out = {}
    for name, c in closes.items():
        if len(c) < 253:
            continue
        out[name] = {"ret_3m_pct": round(float(c.iloc[-1] / c.iloc[-64] - 1) * 100, 2), "ret_12m_pct": round(float(c.iloc[-1] / c.iloc[-253] - 1) * 100, 2),
                     "above_sma200": bool(c.iloc[-1] > c.rolling(200).mean().iloc[-1])}
    return out


def correlations(closes, weeks=52):
    """Rolling one-year correlation of weekly returns between the asset classes."""
    w = pd.DataFrame({k: c.set_axis(c.index.tz_localize(None) if c.index.tz else c.index).resample("W-FRI").last()
                      for k, c in closes.items()}).pct_change().tail(weeks)
    m = w.corr()
    names = list(m.columns)
    return {f"{a} vs {b}": round(float(m.loc[a, b]), 2) for i, a in enumerate(names) for b in names[i + 1:] if not np.isnan(m.loc[a, b])}


def cpi_trend(cpi):
    yoy = (cpi / cpi.shift(12) - 1) * 100
    return {"india_cpi_yoy_pct": round(float(yoy.iloc[-1]), 2), "india_cpi_yoy_3m_ago_pct": round(float(yoy.iloc[-4]), 2),
            "india_cpi_date": cpi.index[-1].date().isoformat(),
            "india_cpi_trend": "rising" if yoy.iloc[-1] > yoy.iloc[-4] else "falling" if yoy.iloc[-1] < yoy.iloc[-4] else "flat"}
