"""Deliverable 2: a financial instruction-tuning dataset with structured reasoning chains.

Each example is a synthetic FACTS block covering the three skills the PRD lists:
  macro asset allocation  rate / inflation context, drift vs ±5%, annual review → BUY / SELL / HOLD per fund
  dual-timeframe synthesis Weekly Core vs Daily Tactical signals, including the same ticker in both sleeves
  news & catalyst validation earnings beats and order wins (High), red flags (Veto), bear regime (Veto all)
The target is the guardrail-correct answer (guard.enforce on the rules) plus a step-by-step reasoning chain, in the chat
format fine-tuning libraries expect: {"messages": [system, user, assistant{thinking, content}]}.

    .venv\\Scripts\\python.exe -m slm.dataset 400     → slm/data/desk_instructions.jsonl
"""
import json
import random
import sys
from pathlib import Path

from . import engine, guard
from .model import SYSTEM

OUT = Path(__file__).with_name("data") / "desk_instructions.jsonl"
TICKERS = ["ALPHAIND", "BETACORP", "GAMMAFIN", "DELTAPOW", "EPSILONIT", "ZETAPHAR", "ETAAUTO", "THETACHEM", "IOTAINFRA", "KAPPABANK"]
RED = ["{c} statutory auditor resigns citing lack of information", "ICRA downgrades {c}'s long-term debt rating to BBB",
       "SEBI bans {c} promoters over fund diversion", "{c} promoter pledge rises to 45% of holding", "Forensic audit flags irregularities at {c}"]
GOOD = ["{c} bags Rs 1,200 crore order from NHAI", "{c} Q2 profit jumps 38%, beats estimates", "{c} raises FY guidance after strong Q2"]
NEUTRAL = ["{c} to hold board meeting on results date", "{c} shares trade flat in a weak market", "{c} AGM held; dividend approved"]


def scenario(rng):
    bull = rng.random() < 0.55
    f = {"as_of": "2026-10-19 16:00",
         "macro": {"rbi_repo_rate_pct": rng.choice([5.25, 5.5, 6.0, 6.5]), "fed_funds_rate_pct": rng.choice([3.5, 3.75, 4.25, 5.0]),
                   "us_10y_real_yield_pct": round(rng.uniform(0.5, 2.8), 2), "us_10y_minus_2y_spread_pct": round(rng.uniform(-0.6, 0.9), 2),
                   "india_cpi_yoy_pct": round(rng.uniform(2, 7), 2), "india_cpi_trend": rng.choice(["rising", "falling", "flat"]),
                   "india_wpi_trend": None, "nifty500_close": round(rng.uniform(19000, 26000), 2),
                   "nifty500_supertrend_weekly": 1 if bull else -1, "nifty500_supertrend_daily": rng.choice([1, -1])},
         "breadth": {"stocks_measured": 495, "pct_above_sma50": round(rng.uniform(15, 80), 1), "pct_above_sma200": round(rng.uniform(25, 80), 1)}}
    total = rng.choice([500000, 1000000, 2500000])
    w = [max(0.02, 0.35 + rng.uniform(-.12, .12)), max(0.02, 0.25 + rng.uniform(-.1, .1)), max(0.02, 0.25 + rng.uniform(-.1, .1)), 0]
    w[3] = max(0.02, 1 - sum(w[:3]))
    holdings = {s: round(total * x / sum(w), 0) for (s, *_), x in zip(engine.SLEEVES, w)}
    f["mf_allocation"] = engine.mf_allocation({}, holdings, rng.random() < 0.15)
    picks = rng.sample(TICKERS, rng.randint(0, 6))
    core, tact, news = [], [], {}
    for t in picks:
        px = round(rng.uniform(100, 5000), 2)
        base = {"ticker": t, "entry_price": px, "rs_percentile": round(rng.uniform(90, 98), 1)}
        if rng.random() < 0.6 or not tact:
            core.append(base | {"stop_loss_price": round(px * 0.9, 2), "stop_rule": "-10% strict", "weekly_rsi14": round(rng.uniform(60.5, 78), 1),
                                "weekly_supertrend": 1, "pct_from_10w_ema": round(rng.uniform(-7, 7), 2)})
        if rng.random() < 0.5:
            tact.append(base | {"stop_loss_price": round(px * (0.7 if bull else 0.9), 2), "stop_rule": "-30% (bull regime)" if bull else "-10% (bear regime)",
                                "daily_rsi14": round(rng.uniform(55, 72), 1), "daily_supertrend": 1, "pct_from_ema9": round(rng.uniform(0, 2), 2),
                                "return_1d_pct": round(rng.uniform(-0.49, 2.5), 2)})
        kind = rng.choices(["red", "good", "beat", "neutral"], [0.2, 0.25, 0.15, 0.4])[0]
        line = rng.choice({"red": RED, "good": GOOD, "neutral": NEUTRAL, "beat": NEUTRAL}[kind]).format(c=t.title())
        surprise = round(rng.uniform(6, 25), 2) if kind == "beat" else None
        news[t] = {"red_flags": [f"{line} (NSE filing, 2026-10-10)"] if kind == "red" else [],
                   "supportive": [f"{line} (news, 2026-10-12)"] if kind == "good" else [],
                   "catalyst_passages": [{"source": "news", "date": "2026-10-12", "text": line}], "risk_passages": [],
                   "earnings_surprise": {"date": "2026-08-01", "eps_estimate": 20.0, "eps_reported": round(20 * (1 + surprise / 100), 2),
                                         "surprise_pct": surprise} if surprise else None,
                   "earnings_beat": bool(surprise), "earnings_miss": False, "documents_searched": rng.randint(3, 30)}
    f |= {"weekly_core_signals": core, "daily_tactical_signals": tact, "news": news, "compliance_disclaimer": guard.DISCLAIMER,
          "exits": [{"ticker": t, "strategy_sleeve": "Weekly Core", "exit_trigger": rng.choice(["Weekly Supertrend flipped to -1",
                                                                                                 "Strict stop: -10.4% from entry (limit -10%)"])}
                    for t in rng.sample(TICKERS, rng.randint(0, 2)) if t not in picks],
          "hedge": {"active": not bull, "orders": []}}
    return f


def reasoning(f, out):
    """The structured reasoning chain the model should follow, step by step."""
    m, a = f["macro"], f["mf_allocation"]
    steps = [f"1. Regime: Nifty 500 weekly Supertrend is {m['nifty500_supertrend_weekly']} → {out['macro_verdict']['regime']}."]
    drifts = [abs(r["drift_pct"]) for r in a["funds"] if r["drift_pct"] is not None]
    steps.append(f"2. Rebalance: largest drift {max(drifts) if drifts else None}% vs ±5% tolerance; annual review flagged {a['annual_review_flagged']} "
                 f"→ {'rebalance using the engine amounts' if a['rebalance_due_by_drift'] or a['annual_review_flagged'] else 'HOLD every fund'}.")
    for d in out["stock_trade_decisions"]:
        n = f["news"].get(d["ticker"], {})
        why = ("bear regime" if m["nifty500_supertrend_weekly"] == -1 else "red flag in news" if n.get("red_flags")
               else "supportive news or earnings beat" if n.get("supportive") or n.get("earnings_beat") else "no supportive news")
        steps.append(f"3. {d['ticker']} ({d['strategy_sleeve']}): {why} → {d['conviction']}; entry {d['entry_price']} and stop {d['stop_loss_price']} copied.")
    both = {d["ticker"] for d in out["stock_trade_decisions"] if d["strategy_sleeve"] == "Weekly Core"} & \
           {d["ticker"] for d in out["stock_trade_decisions"] if d["strategy_sleeve"] == "Daily Tactical"}
    steps += [f"4. {t} is in both sleeves: weekly is the slower trend position with a -10% strict stop; daily is the tactical "
              f"pullback entry with the regime-based stop." for t in sorted(both)]
    steps.append(f"5. Exits: {len(f['exits'])} from FACTS copied. 6. Disclaimer copied exactly.")
    return "\n".join(steps)


def example(f):
    out, _ = guard.enforce({}, f)
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "FACTS:\n" + json.dumps(f, separators=(",", ":"))},
                         {"role": "assistant", "thinking": reasoning(f, out), "content": json.dumps(out, ensure_ascii=False)}]}


def build(n=400, seed=7):
    rng = random.Random(seed)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for _ in range(n):
            fh.write(json.dumps(example(scenario(rng)), ensure_ascii=False) + "\n")
    return OUT


if __name__ == "__main__":
    print(build(int(sys.argv[1]) if len(sys.argv) > 1 else 400))
