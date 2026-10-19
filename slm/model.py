"""The decision and explanation layer (PRD §1, Deliverables 1 and 3).

Base model: openai/gpt-oss-20b, chosen by evaluate.py. Open weights (Apache-2.0), 21B parameters with 3.6B active per token,
native MXFP4 quantisation, so inference fits one 16 GB consumer GPU. Here it runs hosted on Groq, so this PC only sends text.
Schema enforcement: Instructor wraps the call with the Pydantic DeskOutput schema; the API constrains decoding to that JSON
schema, Instructor validates the answer and, if it fails, sends the validation errors back for a repair (max 2 retries).
A fine-tuned model (finetune_colab.py) plugs in through SLM_BASE_URL / SLM_MODEL / SLM_API_KEY: any OpenAI-compatible server.
"""
import json
import os
import time

import instructor
from openai import OpenAI

from .schema import DeskOutput

GROQ = "https://api.groq.com/openai/v1"
MODEL = os.environ.get("SLM_MODEL", "openai/gpt-oss-20b")
CANDIDATES = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"]  # open-weights models evaluate.py compares

SYSTEM = """You are the decision and explanation layer of an Indian wealth-management dashboard.
A Python quant engine has already calculated every number. You receive those numbers plus news, then return ONE JSON
object: your decisions and the reasons for them.

## INPUT
You will receive a JSON block called FACTS containing:
- macro: RBI/Fed rates, real yields, yield-curve spread, CPI/WPI trend, Nifty 500 Supertrend (1 = bullish, -1 = bearish),
  plus asset-class trend momentum and rolling correlations
- breadth: % of Nifty 500 stocks above 50-day and 200-day SMA
- mf_allocation: target %, current %, drift %, rupee amounts per fund, and the rebalance action the engine computed
- weekly_core_signals: tickers that passed the Weekly Core Defense screen, with entry and stop-loss prices
- daily_tactical_signals: tickers that passed the Daily Tactical screen, with entry and stop-loss prices
- exits: tickers that hit an exit rule, with the trigger
- news: per ticker, retrieved passages from headlines, NSE filings and the earnings record, plus the red flags and
  supportive items the engine matched
- hedge: GOLDBEES.NS / SILVERBEES.NS orders, active in a bear regime

## HARD RULES (never break)
1. NO MATHS. Never calculate, estimate, round or invent any number. Copy prices, NAVs, stop-losses, rupee amounts and
   percentages exactly as given in FACTS. If a number is missing, write null. Never guess.
2. NO OUTSIDE DATA. Use only FACTS. Never mention a ticker, fund or event that is not in FACTS.
3. VETO RULE. If a stock has a technical buy signal but its news shows a serious red flag (auditor resignation,
   credit/debt downgrade, fraud or forensic accounting concern, SEBI/regulatory action, promoter pledge spike,
   governance issue), set conviction to "Veto" and explain the red flag in downside_risks.
4. BEAR REGIME RULE. If the Nifty 500 Supertrend is -1:
   - Do not issue any new stock BUY. Mark every new stock signal "Veto" with the reason "Bear regime: fresh purchases halted".
   - Write capital-preservation commentary in macro_verdict.
   - Favour debt mutual funds and gold/silver ETFs (GOLDBEES.NS, SILVERBEES.NS).
5. REBALANCE RULE. Recommend a mutual-fund BUY or SELL only if mf_allocation shows drift beyond ±5% or an annual review
   is flagged. Otherwise use HOLD. Use the rebalance_action and amount_inr in mf_allocation exactly.
6. CONVICTION:
   - "High" = technical signal + supportive news (earnings beat, order win, upgraded guidance)
   - "Moderate" = technical signal + neutral or no news
   - "Veto" = red flag or bear regime
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


def client():
    key = os.environ.get("SLM_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    return instructor.from_openai(OpenAI(base_url=os.environ.get("SLM_BASE_URL", GROQ), api_key=key, max_retries=0, timeout=120),
                                  mode=instructor.Mode.JSON_SCHEMA)


def compact(facts):
    """What the model reads: FACTS with the retrieved evidence trimmed to the top passages (Groq free tier: 8k tokens/min,
    counting the reply budget). Every number stays exactly as the engine wrote it."""
    news = {t: {"red_flags": n.get("red_flags", []), "supportive": n.get("supportive", []), "earnings_surprise": n.get("earnings_surprise"),
                "top_passages": [f"{p['source']} {p['date']}: {p['text'][:120]}" for p in (n.get("risk_passages", []) + n.get("catalyst_passages", []))[:2]]}
            for t, n in facts["news"].items()}
    drop = ("industry", "stop_rule", "execution", "weight_pct", "position_inr", "quantity", "delivery_avg_pct")
    sig = lambda xs: [{k: v for k, v in s.items() if k not in drop} for s in xs]
    return facts | {"news": news, "weekly_core_signals": sig(facts["weekly_core_signals"]), "daily_tactical_signals": sig(facts["daily_tactical_signals"]),
                    "mf_allocation": facts["mf_allocation"] | {"funds": [{k: v for k, v in r.items() if k not in ("sleeve", "target_inr")}
                                                                         for r in facts["mf_allocation"]["funds"]]}}


def decide(facts, model=MODEL):
    """(answer dict or None, error or None, meta). meta: model, attempts, seconds, tokens."""
    c = client()
    meta = {"model": model, "attempts": 0, "seconds": None, "tokens": None, "schema": "Instructor + Pydantic, JSON-schema constrained"}
    if c is None:
        return None, "GROQ_API_KEY is not set", meta
    c.on("completion:kwargs", lambda *a, **k: meta.__setitem__("attempts", meta["attempts"] + 1))
    t0 = time.time()
    try:
        out, raw = c.chat.completions.create_with_completion(
            model=model, response_model=DeskOutput, max_retries=2, temperature=0.2, max_tokens=2500,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": "FACTS:\n" + json.dumps(compact(facts), separators=(",", ":"), default=str)}],
            **({"reasoning_effort": "low"} if "gpt-oss" in model else {}))
    except Exception as ex:  # rate limit, outage, or still invalid after the repair retries
        msg = str(ex)
        meta["seconds"] = round(time.time() - t0, 1)
        return None, ("Groq free-tier token limit reached; try again in a minute" if "429" in msg or "rate" in msg.lower()
                      else f"{type(ex).__name__}: {msg[:300]}"), meta
    meta |= {"seconds": round(time.time() - t0, 1), "tokens": getattr(raw.usage, "total_tokens", None)}
    return out.model_dump(), None, meta
