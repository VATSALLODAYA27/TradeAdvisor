"""Guardrails after the model (PRD §4). The final output is rebuilt from FACTS: every number is copied from FACTS, tickers not in
FACTS are dropped, missing ones are added, the veto / bear-regime / conviction / rebalance rules are applied in code, and any
number in the model's prose that FACTS doesn't contain is tagged [unverified]. With no model answer the same function returns
a complete rule-based output. Every change is listed in `fixes`."""
import re

DISCLAIMER = ("Investments in securities market are subject to market risks. Read all related documents carefully before investing. "
              "The creator of this tool is not registered with SEBI as an Investment Adviser or Research Analyst. This is "
              "automated, rule-based research output for education only, not personalised investment advice. Past performance "
              "does not guarantee future returns. Consult a SEBI-registered adviser before acting.")
RULE_NUMBERS = {0.5, 1, 2, 3, 5, 6, 7, 9, 10, 12, 14, 20, 30, 50, 52, 55, 60, 90, 98, 100, 200, 500}  # indicator names, rule limits
NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers(obj, out=None):
    """Every number in FACTS (values and numbers inside its strings), rounded to 2 dp."""
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(round(abs(float(obj)), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            numbers(v, out)
    elif isinstance(obj, str):
        out |= {round(float(m.replace(",", "").rstrip(".")), 2) for m in NUM.findall(obj) if m.replace(",", "").rstrip(".")}
    return out


def check_text(text, allowed, where, fixes):
    def sub(m):
        raw = m.group().replace(",", "").rstrip(".")
        if not raw:
            return m.group()
        v = round(float(raw), 2)
        if v in allowed or v in RULE_NUMBERS or (v.is_integer() and 1900 <= v <= 2100):
            return m.group()
        fixes.append(f"{where}: number {m.group()} is not in FACTS, marked unverified")
        return f"{m.group()} [unverified]"
    return NUM.sub(sub, text or "")


def _tech(s, sleeve):
    if sleeve == "Weekly Core":
        return (f"RS percentile {s['rs_percentile']}, weekly RSI(14) {s['weekly_rsi14']}, weekly Supertrend 1, "
                f"{s['pct_from_10w_ema']}% from the 10-week EMA.")
    return (f"Daily RSI(14) {s['daily_rsi14']}, Supertrend 1, SMA 50 above SMA 200, {s['pct_from_ema9']}% above EMA 9 "
            f"(pullback band), 1-day return {s['return_1d_pct']}%.")


def enforce(ans, f):
    """(final output in the PRD schema, list of fixes)."""
    ans, fixes = ans if isinstance(ans, dict) else {}, []
    allowed = numbers(f)
    bear = f["macro"]["nifty500_supertrend_weekly"] == -1
    text = lambda v, where, default: check_text(v, allowed, where, fixes) if isinstance(v, str) and v.strip() else default

    mv = ans.get("macro_verdict") or {}
    reg = "Bearish" if bear else mv.get("regime") if mv.get("regime") in ("Bullish", "Neutral") else "Bullish"
    if mv.get("regime") and mv["regime"] != reg:
        fixes.append(f"macro_verdict.regime {mv['regime']} → {reg} (Nifty 500 weekly Supertrend is {f['macro']['nifty500_supertrend_weekly']})")
    b = f["breadth"]
    rationale = text(mv.get("rationale"), "macro rationale",
                     "Nifty 500 weekly Supertrend is -1: capital preservation first; fresh stock purchases are halted and debt funds "
                     "and GOLDBEES.NS / SILVERBEES.NS are favoured." if bear else
                     "Nifty 500 weekly Supertrend is 1: the trend supports new stock entries.")
    if bear and "preserv" not in rationale.lower():
        rationale = rationale.rstrip(". ") + ". Capital preservation first: fresh stock buying is halted and debt funds and gold/silver ETFs are favoured."
    out = {"macro_verdict": {"regime": reg, "rationale": rationale, "breadth_summary": text(
        mv.get("breadth_summary"), "breadth_summary",
        f"{b.get('pct_above_sma50')}% of Nifty 500 stocks are above their 50-day SMA and {b.get('pct_above_sma200')}% above their 200-day SMA.")}}

    model_mf = {o.get("fund_name"): o for o in ans.get("mutual_fund_rebalance_orders") or [] if isinstance(o, dict)}
    out["mutual_fund_rebalance_orders"] = []
    for r in f["mf_allocation"]["funds"]:
        m = model_mf.get(r["fund_name"], {})
        default = (f"Drift {r['drift_pct']}% vs ±{f['mf_allocation']['drift_tolerance_pct']}% tolerance (target {r['target_pct']}%, now "
                   f"{r['current_pct']}%)" + (" and the annual review is due." if f["mf_allocation"]["annual_review_flagged"] else ".")
                   + (" Rebalancing every sleeve back to target." if r["rebalance_action"] != "HOLD" else "")
                   if r["drift_pct"] is not None else "No holdings entered for this sleeve yet.")
        if m and (m.get("action"), m.get("amount_inr")) != (r["rebalance_action"], r["amount_inr"]):
            fixes.append(f"{r['fund_name']}: model said {m.get('action')} {m.get('amount_inr')}, engine says {r['rebalance_action']} {r['amount_inr']}")
            m = {}  # its reason argued for the wrong action
        out["mutual_fund_rebalance_orders"].append({"fund_name": r["fund_name"], "action": r["rebalance_action"], "amount_inr": r["amount_inr"],
                                                    "reason": text(m.get("reason"), f"{r['fund_name']} reason", default)})

    model_st = {(o.get("ticker"), o.get("strategy_sleeve")): o for o in ans.get("stock_trade_decisions") or [] if isinstance(o, dict)}
    sleeves = (("Weekly Core", "weekly_core_signals"), ("Daily Tactical", "daily_tactical_signals"))
    known = {(s["ticker"], sl) for sl, k in sleeves for s in f[k]}
    for k in set(model_st) - known:
        fixes.append(f"dropped {k[0]} ({k[1]}): not a signal in FACTS")
    out["stock_trade_decisions"] = []
    for sleeve, key in sleeves:
        for s in f[key]:
            m, nw = model_st.get((s["ticker"], sleeve), {}), f["news"].get(s["ticker"]) or {}
            flags, good = nw.get("red_flags") or [], (nw.get("supportive") or []) + (
                [f"Earnings beat: EPS {nw['earnings_surprise']['eps_reported']} vs estimate {nw['earnings_surprise']['eps_estimate']} "
                 f"({nw['earnings_surprise']['surprise_pct']}% surprise)"] if nw.get("earnings_beat") else [])
            conv = "Veto" if bear or flags else ("High" if good else "Moderate")
            if m.get("conviction") == "Veto" and conv != "Veto":  # the model may veto on a risk the patterns missed
                conv = "Veto"
            if m.get("conviction") and m["conviction"] != conv:
                fixes.append(f"{s['ticker']} ({sleeve}): conviction {m['conviction']} → {conv}")
            for fld in ("entry_price", "stop_loss_price"):
                if m.get(fld) is not None and m[fld] != s[fld]:
                    fixes.append(f"{s['ticker']} ({sleeve}): {fld} {m[fld]} → {s[fld]} (copied from FACTS)")
            said = text(m.get("downside_risks"), f"{s['ticker']} risks", "")
            risk = ("Bear regime: fresh purchases halted. " if bear and "bear regime" not in said.lower() else "") \
                + (f"Red flag: {flags[0]}. " if flags and flags[0][:40].lower() not in said.lower() else "")
            out["stock_trade_decisions"].append({
                "ticker": s["ticker"], "strategy_sleeve": sleeve, "conviction": conv,
                "entry_price": s["entry_price"], "stop_loss_price": s["stop_loss_price"],
                "technical_rationale": text(m.get("technical_rationale"), f"{s['ticker']} technical", _tech(s, sleeve)),
                "fundamental_catalyst": text(m.get("fundamental_catalyst"), f"{s['ticker']} catalyst",
                                             f"Supportive: {good[0]}" if good else "No supportive news, filings or earnings beat found."),
                "downside_risks": (risk + said).strip() or f"Stop-loss at {s['stop_loss_price']} ({s['stop_rule']}); momentum can reverse quickly.",
            })

    model_ex = {o.get("ticker"): o for o in ans.get("portfolio_exits") or [] if isinstance(o, dict)}
    out["portfolio_exits"] = [{"ticker": x["ticker"], "exit_trigger": x["exit_trigger"]} for x in f["exits"]]
    for t in set(model_ex) - {x["ticker"] for x in f["exits"]}:
        fixes.append(f"dropped exit {t}: not in FACTS exits")
    if ans.get("compliance_disclaimer") and ans["compliance_disclaimer"] != DISCLAIMER:
        fixes.append("compliance_disclaimer replaced with the exact text")
    out["compliance_disclaimer"] = DISCLAIMER
    return out, fixes
