"""AI Portfolio Desk: the SLM requirement doc in three layers.

1. facts()   Python quant engine. Computes every number: Nifty 500 regime, breadth, the Weekly Core and Daily Tactical
             screens with entries and stops, mutual-fund drift and rebalance amounts, exits, macro, news red flags.
2. decide()  Small open-weights language model (gpt-oss-20b on Groq) reads FACTS and returns the decision JSON.
3. enforce() Guardrails. Rebuilds the output from FACTS: copies every number from FACTS, drops tickers that aren't in
             FACTS, applies the bear-regime, veto, conviction and rebalance rules in code, and flags numbers in the
             model's text that FACTS doesn't contain. With no model answer it still returns a complete rule-based output.
Not investment advice; the author is not SEBI-registered.
"""
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests
import yfinance as yf

import data
import news
import paper

MODEL = "openai/gpt-oss-20b"  # open weights, ~21B params (3.6B active); runs on one 16 GB GPU, so it fits the "SLM" brief
NIFTY500 = "^CRSLDX"
FILE = Path(__file__).with_name("desk.json")  # your fund holdings, repo rate and last review date (gitignored)
DRIFT = 5.0  # ± % drift that triggers a rebalance
SLEEVES = [  # sleeve, target %, default fund (Direct Plan, Growth). Fund names are editable on the tab.
    ("International Equity", 35, "Motilal Oswal Nasdaq 100 FOF - Direct Growth"),
    ("Gold", 25, "Nippon India Gold Savings Fund - Direct Growth"),
    ("Bonds / Fixed Income", 25, "HDFC Short Term Debt Fund - Direct Growth"),
    ("Indian Equity", 15, "UTI Nifty 50 Index Fund - Direct Growth"),
]
HEDGE_ETFS = ["GOLDBEES.NS", "SILVERBEES.NS"]
DISCLAIMER = ("Investments in securities market are subject to market risks. Read all related documents carefully before investing. "
              "The creator of this tool is not registered with SEBI as an Investment Adviser or Research Analyst. This is "
              "automated, rule-based research output for education only, not personalised investment advice. Past performance "
              "does not guarantee future returns. Consult a SEBI-registered adviser before acting.")
RED_FLAG = re.compile(
    r"auditor\w*\s+(resign|quit|exit)|resign\w*\s+as\s+auditor|(credit|debt|bond|ncd|crisil|icra|care|moody|fitch|s&p|india ratings)"
    r"\b.{0,40}downgrad|downgrad\w*.{0,40}\b(credit|debt|bonds?|ncd)|fraud|forensic|siphon|accounting\s+(irregular|lapse)|"
    r"sebi\s+(order|bans?|barr|penal|show.cause|notice|probe|action)|pledge|governance|default|insolven|\bed\s+(raid|probe)|"
    r"income.tax\s+raid|whistle.?blow|rbi\s+(cancel|bans?|penal|restrict|curb|action|imposes)|licen[cs]e\s+(cancel|revok|suspend)|"
    r"(cancel|revok|suspend)\w*\s+.{0,30}licen[cs]e", re.I)
SUPPORTIVE = re.compile(r"\bbeats?\b|order\s+(win|worth)|(bags|wins|secures|receives)\b.{0,30}order|upgrad|raises?\s+guidance|"
                        r"record\s+(profit|revenue)|profit\s+(jumps|surges|rises|soars)|strong\s+q\d", re.I)

SYSTEM = """You are the decision and explanation layer of an Indian wealth-management dashboard.
A Python quant engine has already calculated every number. You receive those numbers plus news, then return ONE JSON
object: your decisions and the reasons for them.

## INPUT
A JSON block called FACTS containing:
- macro: RBI/Fed rates, real yields, yield-curve spread, CPI/WPI trend, Nifty 500 Supertrend (1 = bullish, -1 = bearish)
- breadth: % of Nifty 500 stocks above 50-day and 200-day SMA
- mf_allocation: target %, current %, drift %, rupee amounts per fund, and the rebalance action the engine computed
- weekly_core_signals / daily_tactical_signals: tickers that passed each screen, with entry and stop-loss prices
- exits: tickers that hit an exit rule, with the trigger
- news: recent headlines per ticker, plus red_flags and supportive headlines the engine matched
- hedge: GOLDBEES.NS / SILVERBEES.NS prices, active in a bear regime

## HARD RULES (never break)
1. NO MATHS. Never calculate, estimate, round or invent any number. Copy prices, stop-losses, rupee amounts and
   percentages exactly as given in FACTS. If a number is missing, write null. Never guess.
2. NO OUTSIDE DATA. Use only FACTS. Never mention a ticker, fund or event that is not in FACTS.
3. VETO RULE. If a stock has a technical buy signal but its news shows a serious red flag (auditor resignation,
   credit/debt downgrade, fraud or forensic accounting concern, SEBI/regulatory action, promoter pledge spike,
   governance issue), set conviction to "Veto" and explain the red flag in downside_risks.
4. BEAR REGIME RULE. If the Nifty 500 Supertrend is -1: do not issue any new stock BUY; mark every new stock signal
   "Veto" with the reason "Bear regime: fresh purchases halted"; write capital-preservation commentary in
   macro_verdict; favour debt mutual funds and gold/silver ETFs (GOLDBEES.NS, SILVERBEES.NS).
5. REBALANCE RULE. Use the action and amount_inr in mf_allocation exactly. They are BUY or SELL only when drift is
   beyond ±5% or an annual review is flagged; otherwise HOLD with amount_inr null.
6. CONVICTION: "High" = technical signal + supportive news (earnings beat, order win, upgraded guidance);
   "Moderate" = technical signal + neutral or no news; "Veto" = red flag or bear regime.
7. OUTPUT ONLY VALID JSON in the schema below. No text before or after it. No markdown.
8. Always include compliance_disclaimer exactly as given in FACTS.

## OUTPUT SCHEMA
{"macro_verdict": {"regime": "Bullish"|"Bearish"|"Neutral", "breadth_summary": "string", "rationale": "string"},
 "mutual_fund_rebalance_orders": [{"fund_name": "string", "action": "BUY"|"SELL"|"HOLD", "amount_inr": number|null, "reason": "string"}],
 "stock_trade_decisions": [{"ticker": "string", "strategy_sleeve": "Weekly Core"|"Daily Tactical", "conviction": "High"|"Moderate"|"Veto",
   "entry_price": number|null, "stop_loss_price": number|null, "technical_rationale": "string", "fundamental_catalyst": "string",
   "downside_risks": "string"}],
 "portfolio_exits": [{"ticker": "string", "exit_trigger": "string"}],
 "compliance_disclaimer": "string"}

## STYLE
- Rationales: 1-3 short sentences, plain English, name the specific indicator or news item.
- Explain weekly vs daily differences when a ticker appears in both sleeves.
- If a list has no items, return an empty array []."""


# ---------- settings (your holdings) ----------

def load_settings():
    try:
        return json.loads(FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {"funds": {s: f for s, _, f in SLEEVES}, "holdings": {s: 0 for s, _, _ in SLEEVES}, "repo_rate": None, "last_review": None}


def save_settings(cfg):
    FILE.write_text(json.dumps(cfg, indent=1))


# ---------- quant engine ----------

def _weekly(d):
    return d.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()


def _st_dir(d):
    return int(data.indicators(d, data.load_settings())["supertrend_dir"].iloc[-1])


def regime(d):
    """Nifty 500 weekly and daily Supertrend (1 bull / -1 bear) and its last close. The weekly one sets the regime."""
    return {"nifty500_close": round(float(d["Close"].iloc[-1]), 2), "nifty500_supertrend_weekly": _st_dir(_weekly(d)),
            "nifty500_supertrend_daily": _st_dir(d)}


def stock_features(d):
    """Every screen input for one stock's daily candles. None when history is too short."""
    if len(d) < 220:
        return None
    s = data.load_settings()
    c, w = d["Close"], _weekly(d)
    ind, wind = data.indicators(d, s), data.indicators(w, s)
    sma50, sma200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
    ema9, ema10w = data.ema(c, 9).iloc[-1], data.ema(w["Close"], 10).iloc[-1]
    last = float(c.iloc[-1])
    return {
        "close": round(last, 2), "ret_6m": float(last / c.iloc[-127] - 1), "ret_1d_pct": round(float(last / c.iloc[-2] - 1) * 100, 2),
        "sma50": float(sma50), "sma200": float(sma200), "above_sma50": last > sma50, "above_sma200": last > sma200,
        "rsi_d": round(float(data.rsi(c, 14).iloc[-1]), 1), "rsi_w": round(float(data.rsi(w["Close"], 14).iloc[-1]), 1),
        "st_d": int(ind["supertrend_dir"].iloc[-1]), "st_w": int(wind["supertrend_dir"].iloc[-1]),
        "pct_from_ema10w": round(float(last / ema10w - 1) * 100, 2), "pct_from_ema9": round(float(last / ema9 - 1) * 100, 2),
        "pct_from_52w_high": round(float(last / d["High"].tail(252).max() - 1) * 100, 2),
        "vol_ratio": round(float(d["Volume"].iloc[-1] / d["Volume"].iloc[-21:-1].mean()), 2) if d["Volume"].iloc[-21:-1].mean() else None,
    }


def screens(feats, bull):
    """Weekly Core and Daily Tactical signals from {ticker: features}. RS = percentile rank of 6-month return in the universe."""
    rs = pd.Series({t: f["ret_6m"] for t, f in feats.items()}).rank(pct=True) * 100
    core, tact = [], []
    for t, f in feats.items():
        r = round(float(rs[t]), 1)
        base = {"ticker": t, "entry_price": f["close"], "rs_percentile": r, "pct_from_52w_high": f["pct_from_52w_high"], "volume_vs_20d": f["vol_ratio"]}
        if 90 <= r <= 98 and f["rsi_w"] > 60 and f["st_w"] == 1 and abs(f["pct_from_ema10w"]) <= 7:
            core.append(base | {"stop_loss_price": round(f["close"] * 0.90, 2), "stop_rule": "-10% fixed",
                                "weekly_rsi14": f["rsi_w"], "weekly_supertrend": f["st_w"], "pct_from_10w_ema": f["pct_from_ema10w"]})
        # shortcut: "EMA 9 pullback band" read as close 0-2% above EMA 9; widen the band in screens() if it's too strict
        if (f["sma50"] > f["sma200"] and f["above_sma200"] and f["st_d"] == 1 and f["rsi_d"] >= 55 and f["ret_1d_pct"] > -0.5
                and 0 <= f["pct_from_ema9"] <= 2):
            stop = 0.70 if bull else 0.90
            tact.append(base | {"stop_loss_price": round(f["close"] * stop, 2), "stop_rule": "-30% (bull regime)" if bull else "-10% (bear regime)",
                                "daily_rsi14": f["rsi_d"], "daily_supertrend": f["st_d"], "pct_from_ema9": f["pct_from_ema9"],
                                "return_1d_pct": f["ret_1d_pct"]})
    top = lambda xs: sorted(xs, key=lambda x: -x["rs_percentile"])[:10]  # 10 equal-weight positions per sleeve
    return top(core), top(tact)


def breadth(feats):
    n = len(feats)
    return {"stocks_measured": n, "pct_above_sma50": round(float(sum(f["above_sma50"] for f in feats.values())) / n * 100, 1),
            "pct_above_sma200": round(float(sum(f["above_sma200"] for f in feats.values())) / n * 100, 1)} if n else {}


def mf_allocation(cfg, review_due):
    """Target vs current per sleeve. The engine decides the action and rupee amount, so the model never does arithmetic."""
    hold = {s: float(cfg["holdings"].get(s) or 0) for s, _, _ in SLEEVES}
    total = sum(hold.values())
    rows = []
    for s, tgt, _ in SLEEVES:
        cur = hold[s] / total * 100 if total else None
        drift = None if cur is None else round(cur - tgt, 2)
        rows.append({"sleeve": s, "fund_name": cfg["funds"].get(s) or s, "target_pct": tgt, "current_inr": round(hold[s], 2),
                     "current_pct": None if cur is None else round(cur, 2), "drift_pct": drift,
                     "target_inr": round(total * tgt / 100, 2) if total else None})
    due_drift = any(r["drift_pct"] is not None and abs(r["drift_pct"]) > DRIFT for r in rows)
    for r in rows:
        gap = None if r["target_inr"] is None else round(r["target_inr"] - r["current_inr"], 2)
        act = ("BUY" if gap > 0 else "SELL" if gap < 0 else "HOLD") if (due_drift or review_due) and gap else "HOLD"
        r |= {"rebalance_action": act, "amount_inr": abs(gap) if act != "HOLD" else None}
    return {"total_inr": round(total, 2), "drift_tolerance_pct": DRIFT, "rebalance_due_by_drift": due_drift,
            "annual_review_flagged": review_due, "funds": rows}


def exits(held, feats, bull):
    """Exit triggers for stocks you hold in Paper Trading."""
    out = []
    for t, entry in held.items():
        f = feats.get(t)
        if not f:
            continue
        lim = -30 if bull else -10
        pl = round((f["close"] / entry - 1) * 100, 2)
        why = ([f"Stop-loss: {pl}% from entry {entry} (limit {lim}% in a {'bull' if bull else 'bear'} regime)"] if pl <= lim else []) \
            + (["Daily Supertrend flipped to -1"] if f["st_d"] == -1 else []) + (["Close below 200-day SMA"] if not f["above_sma200"] else [])
        if why:
            out.append({"ticker": t, "entry_price": entry, "close": f["close"], "exit_trigger": "; ".join(why)})
    return out


def _fred(series):
    df = pd.read_csv(io.StringIO(requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=20).text))
    df = df[pd.to_numeric(df.iloc[:, 1], errors="coerce").notna()]
    return pd.Series(df.iloc[:, 1].astype(float).values, index=pd.to_datetime(df.iloc[:, 0]))


def macro(cfg):
    """FRED for the Fed rate, US real yield, US curve and India CPI; the RBI repo rate is what you type on the tab. Missing = null."""
    out = {"rbi_repo_rate_pct": cfg.get("repo_rate"), "india_wpi_trend": None}
    for key, sid in (("fed_funds_rate_pct", "FEDFUNDS"), ("us_10y_real_yield_pct", "DFII10"), ("us_10y_minus_2y_spread_pct", "T10Y2Y")):
        try:
            s = _fred(sid)
            out[key], out[key.replace("_pct", "_date")] = round(float(s.iloc[-1]), 2), str(s.index[-1].date())
        except Exception:
            out[key] = None
    try:
        cpi = _fred("INDCPIALLMINMEI")
        yoy = (cpi / cpi.shift(12) - 1) * 100
        out |= {"india_cpi_yoy_pct": round(float(yoy.iloc[-1]), 2), "india_cpi_yoy_3m_ago_pct": round(float(yoy.iloc[-4]), 2),
                "india_cpi_date": str(cpi.index[-1].date()),
                "india_cpi_trend": "rising" if yoy.iloc[-1] > yoy.iloc[-4] else "falling" if yoy.iloc[-1] < yoy.iloc[-4] else "flat"}
        if out["rbi_repo_rate_pct"] is not None:
            out["india_real_repo_rate_pct"] = round(out["rbi_repo_rate_pct"] - out["india_cpi_yoy_pct"], 2)
    except Exception:
        out |= {"india_cpi_yoy_pct": None, "india_cpi_trend": None}
    return out


def ticker_news(t, company):
    """Last 30 days of headlines about one company with the engine's red-flag and supportive matches. Searches by company
    name and keeps headlines naming it (a ticker search pulls in unrelated stories)."""
    word = re.sub(r"\b(ltd|limited|the|india|of|and)\b\.?", "", company, flags=re.I).split()[0].lower()  # "Ather Energy Ltd." -> "ather"
    items = news.rss(news.GOOGLE.format(quote_plus(f'"{company.removesuffix(" Ltd.").removesuffix(" Limited")}" share')), n=15, days=30)
    titles = [x["title"][:110] for x in items if word in x["title"].lower() or t.lower() in x["title"].lower()]
    return {"headlines": titles[:3], "red_flags": [h for h in titles if RED_FLAG.search(h)][:3],
            "supportive": [h for h in titles if SUPPORTIVE.search(h)][:3]}


def facts(cfg, review_due=False, progress=None):
    """The whole FACTS block. progress(fraction, text) for the UI."""
    say = progress or (lambda f, t: None)
    say(0.02, "Nifty 500 list…")
    r = data.NSE.get("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv", timeout=15)
    r.raise_for_status()
    lst = pd.read_csv(io.StringIO(r.text)).dropna(subset=["Symbol"])
    universe, company = lst["Symbol"].tolist(), dict(zip(lst["Symbol"], lst["Company Name"]))
    held = {p["symbol"]: p["entry"] for p in paper.load()["positions"] if not p.get("kind") and paper.currency(p["symbol"]) == "INR"}
    names = list(dict.fromkeys(universe + list(held)))
    say(0.05, f"Downloading 2 years of daily candles for {len(names)} stocks (about a minute)…")
    raw = yf.download([f"{t}.NS" for t in names] + [NIFTY500] + HEDGE_ETFS, period="2y", interval="1d", group_by="ticker",
                      threads=True, progress=False, auto_adjust=False)
    say(0.6, "Computing features…")
    feats = {}
    for t in names:
        try:
            if (f := stock_features(raw[f"{t}.NS"].dropna(subset=["Close"]))) is not None:
                feats[t] = f
        except Exception:
            pass
    reg = regime(raw[NIFTY500].dropna(subset=["Close"]))
    bull = reg["nifty500_supertrend_weekly"] == 1
    core, tact = screens({t: f for t, f in feats.items() if t in universe}, bull)
    say(0.75, "News for the signals…")
    tickers = list(dict.fromkeys(x["ticker"] for x in core + tact))
    with ThreadPoolExecutor(8) as pool:
        got = dict(zip(tickers, pool.map(lambda t: _safe_news(t, company.get(t, t)), tickers)))
    say(0.9, "Macro data…")
    hedge = {e: round(float(raw[e]["Close"].dropna().iloc[-1]), 2) for e in HEDGE_ETFS if len(raw[e]["Close"].dropna())}
    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "macro": macro(cfg) | reg,
        "breadth": breadth({t: f for t, f in feats.items() if t in universe}),
        "mf_allocation": mf_allocation(cfg, review_due),
        "weekly_core_signals": core, "daily_tactical_signals": tact,
        "exits": exits(held, feats, bull),
        "news": {t: n for t, n in got.items() if n},
        "hedge": {"active": not bull, "etf_prices": hedge,
                  "note": "Bear regime: stock buying frozen; unallocated cash goes to these ETFs" if not bull else "Inactive in a bull regime"},
        "compliance_disclaimer": DISCLAIMER,
    }


def _safe_news(t, company):
    try:
        return ticker_news(t, company)
    except Exception:
        return None


# ---------- decision layer ----------

def decide(f):
    """The model's JSON answer, or (None, reason) when the model can't be reached. Returns (answer, error)."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None, "GROQ_API_KEY is not set"
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=90, json={
        "model": MODEL, "response_format": {"type": "json_object"}, "temperature": 0.2, "reasoning_effort": "low",
        "max_completion_tokens": 4000,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "FACTS:\n" + json.dumps(f, separators=(",", ":"))}]})
    if r.status_code == 429:
        return None, "Groq free-tier token limit reached; try again in a minute"
    if not r.ok:
        return None, f"Groq HTTP {r.status_code}"
    try:
        return json.loads(r.json()["choices"][0]["message"]["content"]), None
    except (KeyError, ValueError, TypeError):
        return None, "the model returned something that isn't JSON"


# ---------- guardrails ----------

RULE_NUMBERS = {5, 7, 9, 10, 14, 50, 52, 55, 60, 90, 98, 200, 30, 0.5, 1, -1, 2, 3, 6, 20, 500, 100}  # indicator names and rule limits


def _numbers(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(round(abs(float(obj)), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)
    elif isinstance(obj, str):
        for m in re.findall(r"\d[\d,]*\.?\d*", obj):
            out.add(round(float(m.replace(",", "").rstrip(".")), 2))
    return out


def _check_text(text, allowed, where, fixes):
    """Mark numbers in model text that FACTS doesn't contain (the model may not compute or invent numbers)."""
    def sub(m):
        v = round(float(m.group().replace(",", "").rstrip(".")), 2)
        if v in allowed or v in RULE_NUMBERS or (v.is_integer() and 1900 <= v <= 2100):
            return m.group()
        fixes.append(f"{where}: number {m.group()} is not in FACTS, marked unverified")
        return f"{m.group()} [unverified]"
    return re.sub(r"\d[\d,]*\.?\d*(?=\D|$)", sub, text or "")


def enforce(ans, f):
    """The final output, built from FACTS with the model's words where they pass the rules. Returns (output, fixes)."""
    ans, fixes = ans if isinstance(ans, dict) else {}, []
    allowed = _numbers(f)
    bear = f["macro"]["nifty500_supertrend_weekly"] == -1
    text = lambda v, where, default: _check_text(v, allowed, where, fixes) if isinstance(v, str) and v.strip() else default

    mv = ans.get("macro_verdict") or {}
    reg = "Bearish" if bear else mv.get("regime") if mv.get("regime") in ("Bullish", "Neutral") else "Bullish"
    if mv.get("regime") and mv.get("regime") != reg:
        fixes.append(f"macro_verdict.regime {mv.get('regime')} → {reg} (Nifty 500 weekly Supertrend is {f['macro']['nifty500_supertrend_weekly']})")
    b = f["breadth"]
    out = {"macro_verdict": {
        "regime": reg,
        "breadth_summary": text(mv.get("breadth_summary"), "breadth_summary",
                                f"{b.get('pct_above_sma50')}% of Nifty 500 stocks are above their 50-day SMA and "
                                f"{b.get('pct_above_sma200')}% above their 200-day SMA."),
        "rationale": text(mv.get("rationale"), "macro rationale",
                          "Nifty 500 weekly Supertrend is -1: fresh stock purchases are halted; preserve capital and favour debt funds "
                          "and GOLDBEES.NS / SILVERBEES.NS." if bear else "Nifty 500 weekly Supertrend is 1: the trend supports new stock entries.")}}
    if bear and "preserv" not in out["macro_verdict"]["rationale"].lower():
        out["macro_verdict"]["rationale"] = out["macro_verdict"]["rationale"].rstrip(". ") + ". Capital preservation first: fresh stock buying is halted and debt funds and gold/silver ETFs are favoured."

    model_mf = {o.get("fund_name"): o for o in ans.get("mutual_fund_rebalance_orders") or [] if isinstance(o, dict)}
    out["mutual_fund_rebalance_orders"] = []
    for r in f["mf_allocation"]["funds"]:
        m = model_mf.get(r["fund_name"], {})
        default = (f"Drift {r['drift_pct']}% vs ±{DRIFT}% tolerance (target {r['target_pct']}%, now {r['current_pct']}%)"
                   + (" and the annual review is due." if f["mf_allocation"]["annual_review_flagged"] else ".")
                   + (" Rebalancing every sleeve back to target." if r["rebalance_action"] != "HOLD" else "")
                   if r["drift_pct"] is not None else "No holdings entered for this sleeve yet.")
        if m and (m.get("action"), m.get("amount_inr")) != (r["rebalance_action"], r["amount_inr"]):
            fixes.append(f"{r['fund_name']}: model said {m.get('action')} {m.get('amount_inr')}, engine says {r['rebalance_action']} {r['amount_inr']}")
            m = {}  # its reason argued for the wrong action
        out["mutual_fund_rebalance_orders"].append({"fund_name": r["fund_name"], "action": r["rebalance_action"], "amount_inr": r["amount_inr"],
                                                    "reason": text(m.get("reason"), f"{r['fund_name']} reason", default)})

    model_st = {(o.get("ticker"), o.get("strategy_sleeve")): o for o in ans.get("stock_trade_decisions") or [] if isinstance(o, dict)}
    known = {(s["ticker"], sl) for sl, k in (("Weekly Core", "weekly_core_signals"), ("Daily Tactical", "daily_tactical_signals")) for s in f[k]}
    for k in set(model_st) - known:
        fixes.append(f"dropped {k[0]} ({k[1]}): not a signal in FACTS")
    out["stock_trade_decisions"] = []
    for sleeve, key in (("Weekly Core", "weekly_core_signals"), ("Daily Tactical", "daily_tactical_signals")):
        for s in f[key]:
            m, nw = model_st.get((s["ticker"], sleeve), {}), f["news"].get(s["ticker"]) or {}
            flags, good = nw.get("red_flags") or [], nw.get("supportive") or []
            conv = "Veto" if bear or flags else ("High" if good else "Moderate")
            if m.get("conviction") == "Veto" and conv != "Veto":  # the model may veto on news the regex missed
                conv = "Veto"
            if m.get("conviction") and m["conviction"] != conv:
                fixes.append(f"{s['ticker']} ({sleeve}): conviction {m['conviction']} → {conv}")
            for fld in ("entry_price", "stop_loss_price"):
                if m.get(fld) is not None and m[fld] != s[fld]:  # a blank is simply filled in
                    fixes.append(f"{s['ticker']} ({sleeve}): {fld} {m[fld]} → {s[fld]} (copied from FACTS)")
            said = text(m.get("downside_risks"), f"{s['ticker']} risks", "")
            risk = ("Bear regime: fresh purchases halted. " if bear and "bear regime" not in said.lower() else "")                 + (f"Red flag in news: {flags[0]}. " if flags else "")
            out["stock_trade_decisions"].append({
                "ticker": s["ticker"], "strategy_sleeve": sleeve, "conviction": conv,
                "entry_price": s["entry_price"], "stop_loss_price": s["stop_loss_price"],
                "technical_rationale": text(m.get("technical_rationale"), f"{s['ticker']} technical", _tech(s, sleeve)),
                "fundamental_catalyst": text(m.get("fundamental_catalyst"), f"{s['ticker']} catalyst",
                                             f"Supportive news: {good[0]}" if good else "No supportive news in the last 30 days."),
                "downside_risks": (risk + said).strip()
                or f"Stop-loss at {s['stop_loss_price']} ({s['stop_rule']}); momentum can reverse quickly.",
            })

    model_ex = {o.get("ticker"): o for o in ans.get("portfolio_exits") or [] if isinstance(o, dict)}
    out["portfolio_exits"] = [{"ticker": x["ticker"], "exit_trigger": x["exit_trigger"]} for x in f["exits"]]
    for t in set(model_ex) - {x["ticker"] for x in f["exits"]}:
        fixes.append(f"dropped exit {t}: not in FACTS exits")
    if ans.get("compliance_disclaimer") and ans["compliance_disclaimer"] != DISCLAIMER:
        fixes.append("compliance_disclaimer replaced with the exact text")
    out["compliance_disclaimer"] = DISCLAIMER
    return out, fixes


def _tech(s, sleeve):
    if sleeve == "Weekly Core":
        return (f"RS percentile {s['rs_percentile']}, weekly RSI(14) {s['weekly_rsi14']}, weekly Supertrend 1, "
                f"{s['pct_from_10w_ema']}% from the 10-week EMA.")
    return (f"Daily RSI(14) {s['daily_rsi14']}, Supertrend 1, SMA 50 above SMA 200, {s['pct_from_ema9']}% above EMA 9 "
            f"(pullback band), 1-day return {s['return_1d_pct']}%.")


def run(cfg, review_due=False, use_model=True, progress=None):
    f = facts(cfg, review_due, progress)
    ans, err = decide(f) if use_model else (None, "model turned off")
    out, fixes = enforce(ans, f)
    return {"facts": f, "model_answer": ans, "model_error": err, "output": out, "fixes": fixes}


if __name__ == "__main__":  # offline self-checks
    sig = {"ticker": "AAA", "entry_price": 100.0, "stop_loss_price": 90.0, "stop_rule": "-10% fixed", "rs_percentile": 95.0,
           "weekly_rsi14": 65.0, "weekly_supertrend": 1, "pct_from_10w_ema": 3.0, "pct_from_52w_high": -2.0, "volume_vs_20d": 1.2}
    cfg = {"funds": {s: f for s, _, f in SLEEVES}, "holdings": {"International Equity": 50000, "Gold": 25000,
                                                                 "Bonds / Fixed Income": 15000, "Indian Equity": 10000}}
    mf = mf_allocation(cfg, False)
    intl = mf["funds"][0]
    assert mf["rebalance_due_by_drift"] and intl["drift_pct"] == 15 and intl["rebalance_action"] == "SELL" and intl["amount_inr"] == 15000
    assert mf["funds"][1]["rebalance_action"] == "HOLD" and mf["funds"][1]["amount_inr"] is None  # gold on target
    assert mf_allocation({"funds": cfg["funds"], "holdings": {"International Equity": 36, "Gold": 25, "Bonds / Fixed Income": 24,
                                                              "Indian Equity": 15}}, False)["funds"][0]["rebalance_action"] == "HOLD"
    f = {"macro": {"nifty500_supertrend_weekly": 1}, "breadth": {"pct_above_sma50": 60.0, "pct_above_sma200": 55.0},
         "mf_allocation": mf, "weekly_core_signals": [sig], "daily_tactical_signals": [], "exits": [],
         "news": {"AAA": {"headlines": [], "red_flags": [], "supportive": ["AAA bags order worth Rs 500 crore"]}}}
    ans = {"macro_verdict": {"regime": "Bullish", "rationale": "Breadth is 60.0% and the market will rise 12.5%."},
           "stock_trade_decisions": [{"ticker": "AAA", "strategy_sleeve": "Weekly Core", "conviction": "Moderate", "entry_price": 101},
                                     {"ticker": "ZZZ", "strategy_sleeve": "Weekly Core", "conviction": "High"}],
           "mutual_fund_rebalance_orders": [{"fund_name": SLEEVES[0][2], "action": "BUY", "amount_inr": 999}]}
    out, fixes = enforce(ans, f)
    d = out["stock_trade_decisions"]
    assert len(d) == 1 and d[0]["entry_price"] == 100.0 and d[0]["conviction"] == "High"  # number copied, supportive news → High
    assert "12.5 [unverified]" in out["macro_verdict"]["rationale"] and "60.0%" in out["macro_verdict"]["rationale"]
    mo = out["mutual_fund_rebalance_orders"][0]
    assert mo["action"] == "SELL" and mo["reason"].startswith("Drift 15.0%") and any("ZZZ" in x for x in fixes)
    f["news"]["AAA"]["red_flags"] = ["AAA auditor resigns citing lapses"]
    assert enforce({}, f)[0]["stock_trade_decisions"][0]["conviction"] == "Veto"
    f["news"]["AAA"]["red_flags"], f["macro"]["nifty500_supertrend_weekly"] = [], -1
    o, _ = enforce({}, f)
    assert o["macro_verdict"]["regime"] == "Bearish" and o["stock_trade_decisions"][0]["conviction"] == "Veto"
    assert "Bear regime" in o["stock_trade_decisions"][0]["downside_risks"] and o["compliance_disclaimer"] == DISCLAIMER
    assert RED_FLAG.search("ICRA downgrades XYZ's debt rating") and RED_FLAG.search("SEBI bans promoters of ABC")
    assert RED_FLAG.search("Paytm shares crash as RBI cancels Paytm Payments Bank licence")
    assert not RED_FLAG.search("XYZ Q2 profit rises 20%") and SUPPORTIVE.search("XYZ bags Rs 200 crore order")
    print("ok")
