"""Offline checks for the desk: indicators, engine maths, RAG ranking and flags, schema, guardrails, dataset.
    .venv\\Scripts\\python.exe -m slm.test_slm"""
import json
import random

import numpy as np
import pandas as pd
from pydantic import ValidationError

from . import dataset, engine, guard, indicators as ind, rag
from .schema import DeskOutput

# indicators: an up-trend has Supertrend 1 and high RSI, a down-trend -1 and low RSI
idx = pd.bdate_range("2024-01-01", periods=300)
up = pd.Series(np.linspace(100, 200, 300), index=idx)
mk = lambda c: pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * .99, "Close": c, "Volume": 1000.0})
assert ind.supertrend(mk(up)).iloc[-1] == 1 and ind.supertrend(mk(up[::-1].set_axis(idx))).iloc[-1] == -1
assert ind.rsi(up).iloc[-1] > 90 and ind.rsi(up[::-1].set_axis(idx)).iloc[-1] < 10
assert engine.features(mk(up))["st_w"] == 1 and engine.features(mk(up.iloc[:100])) is None

# mutual funds: 50/20/20/10 → International 15 points over → rebalance every sleeve with exact amounts
mf = engine.mf_allocation({}, {"International Equity": 50000, "Gold": 20000, "Bonds / Fixed Income": 20000, "Indian Equity": 10000}, False)
assert [(r["rebalance_action"], r["amount_inr"]) for r in mf["funds"]] == [("SELL", 15000), ("BUY", 5000), ("BUY", 5000), ("BUY", 5000)]
inside = engine.mf_allocation({}, {"International Equity": 36, "Gold": 25, "Bonds / Fixed Income": 24, "Indian Equity": 15}, False)
assert all(r["rebalance_action"] == "HOLD" and r["amount_inr"] is None for r in inside["funds"])
assert engine.mf_allocation({}, {"International Equity": 36, "Gold": 25, "Bonds / Fixed Income": 24, "Indian Equity": 15}, True)["funds"][0]["rebalance_action"] == "SELL"

# sizing, hedge, Monday execution, exits
s = engine.size([{"ticker": "A", "entry_price": 333.0}], 1_000_000)[0]
assert s["position_inr"] == 100000 and s["quantity"] == 300 and s["weight_pct"] == 10
h = engine.hedge(False, 100000, {"GOLDBEES.NS": 100.0, "SILVERBEES.NS": 200.0})
assert h["active"] and [o["units"] for o in h["orders"]] == [500, 250] and not engine.hedge(True, 1, {})["active"]
assert engine.next_monday(pd.Timestamp("2026-10-19").date()).isoformat() == "2026-10-26"  # a Monday → the next one
f = {"close": 89.0, "st_w": 1, "st_d": 1, "above_sma200": True}
assert "Strict stop" in engine.exits([{"ticker": "A", "sleeve": "Weekly Core", "entry_price": 100}], {"A": f}, True)[0]["exit_trigger"]
assert engine.exits([{"ticker": "A", "sleeve": "Daily Tactical", "entry_price": 100}], {"A": f}, True) == []  # -11% is inside -30% in a bull
assert engine.exits([{"ticker": "A", "sleeve": "Daily Tactical", "entry_price": 100}], {"A": f}, False)  # but not inside -10% in a bear

# RAG: BM25 ranks the relevant passage first; red flags, supportive news and earnings beats are tagged
docs = rag.documents("Alpha Industries Ltd.", "ALPHAIND",
                     [{"title": "Alpha Industries bags Rs 900 crore order", "source": "ET", "date": "2026-10-10"},
                      {"title": "Tesla deliveries beat estimates", "source": "X", "date": "2026-10-10"}],
                     [{"subject": "Resignation of Statutory Auditor", "text": "The statutory auditor resigns as auditor citing lack of information",
                       "date": "2026-10-11"}], {"date": "2026-08-01", "eps_estimate": 10.0, "eps_reported": 12.0, "surprise_pct": 20.0})
assert len(docs) == 3  # the unrelated Tesla headline is dropped
r = rag.retrieve(docs, {"surprise_pct": 20.0})
assert "auditor" in r["risk_passages"][0]["text"] and r["red_flags"] and r["supportive"] and r["earnings_beat"]
for t in ("ICRA downgrades XYZ's debt rating", "SEBI bans promoters of ABC", "RBI cancels Paytm Payments Bank licence"):
    assert rag.RED_FLAG.search(t), t
assert not rag.RED_FLAG.search("XYZ Q2 profit rises 20%")

# schema: extra keys and bad enums are rejected
ok = {"macro_verdict": {"regime": "Bearish", "breadth_summary": "x", "rationale": "y"}, "mutual_fund_rebalance_orders": [],
      "stock_trade_decisions": [], "portfolio_exits": [], "compliance_disclaimer": guard.DISCLAIMER}
DeskOutput.model_validate(ok)
for bad in ({**ok, "extra": 1}, {**ok, "macro_verdict": {**ok["macro_verdict"], "regime": "Bull"}}):
    try:
        DeskOutput.model_validate(bad)
        raise AssertionError("schema accepted a bad answer")
    except ValidationError:
        pass

# guardrails on a synthetic FACTS block
sig = {"ticker": "AAA", "entry_price": 100.0, "stop_loss_price": 90.0, "stop_rule": "-10% strict", "rs_percentile": 95.0,
       "weekly_rsi14": 65.0, "weekly_supertrend": 1, "pct_from_10w_ema": 3.0}
F = {"macro": {"nifty500_supertrend_weekly": 1}, "breadth": {"pct_above_sma50": 60.0, "pct_above_sma200": 55.0}, "mf_allocation": mf,
     "weekly_core_signals": [sig], "daily_tactical_signals": [], "exits": [],
     "news": {"AAA": {"red_flags": [], "supportive": ["AAA bags order worth Rs 500 crore (news, 2026-10-10)"], "earnings_beat": False}}}
ans = {"macro_verdict": {"regime": "Bullish", "rationale": "Breadth is 60.0% and the market will rise 12.5%."},
       "stock_trade_decisions": [{"ticker": "AAA", "strategy_sleeve": "Weekly Core", "conviction": "Moderate", "entry_price": 101},
                                 {"ticker": "ZZZ", "strategy_sleeve": "Weekly Core", "conviction": "High"}],
       "mutual_fund_rebalance_orders": [{"fund_name": engine.SLEEVES[0][2], "action": "BUY", "amount_inr": 999, "reason": "wrong"}]}
out, fixes = guard.enforce(ans, F)
d = out["stock_trade_decisions"]
assert len(d) == 1 and d[0]["entry_price"] == 100.0 and d[0]["conviction"] == "High"
assert "12.5 [unverified]" in out["macro_verdict"]["rationale"] and "60.0%" in out["macro_verdict"]["rationale"]
mo = out["mutual_fund_rebalance_orders"][0]
assert mo["action"] == "SELL" and mo["amount_inr"] == 15000 and mo["reason"].startswith("Drift 15.0%") and any("ZZZ" in x for x in fixes)
F["news"]["AAA"]["red_flags"] = ["AAA auditor resigns (NSE filing, 2026-10-10)"]
assert guard.enforce({}, F)[0]["stock_trade_decisions"][0]["conviction"] == "Veto"
F["news"]["AAA"]["red_flags"], F["macro"]["nifty500_supertrend_weekly"] = [], -1
o, _ = guard.enforce({}, F)
assert o["macro_verdict"]["regime"] == "Bearish" and o["stock_trade_decisions"][0]["conviction"] == "Veto"
assert "Bear regime: fresh purchases halted" in o["stock_trade_decisions"][0]["downside_risks"] and "preserv" in o["macro_verdict"]["rationale"].lower()
DeskOutput.model_validate(o)  # the guardrail output always fits the schema

# dataset: every example's target fits the schema and carries a reasoning chain
for _ in range(25):
    ex = dataset.example(dataset.scenario(random.Random(_)))
    a = ex["messages"][2]
    DeskOutput.model_validate(json.loads(a["content"]))
    assert a["thinking"].startswith("1. Regime")
print("ok")
