"""Verdict-only multi-agent advisor. Never places orders.

LangGraph: collect -> one node per [section] in rules.toml (in parallel) -> report.
The verdicts come only from your rules. An LLM (Groq, free tier) just explains them and flags conflicts.

    python advisor.py RELIANCE
    python advisor.py NIFTY --only options,hedge
    python advisor.py RELIANCE --exchange BSE --no-llm
"""
import argparse
import json
import operator
import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, TypedDict

import requests
from langgraph.graph import END, START, StateGraph

import option_pick
from data import collect, load_settings, metric_names

RULES_FILE = Path(__file__).with_name("rules.toml")

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}


def load_rules(text):
    """Parse + validate rules.toml text; raises ValueError with a readable message."""
    try:
        rules = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"TOML syntax: {e}")
    for name, section in rules.items():
        if not isinstance(section, dict):
            raise ValueError(f"'{name}' must be a [section]")
        for label, rs in section.items():
            if label == "default":
                continue
            for r in rs if isinstance(rs, list) else [None]:
                ok = isinstance(r, list) and len(r) == 3 and isinstance(r[0], str) and (
                    (r[1] == "between" and isinstance(r[2], list) and len(r[2]) == 2)
                    or (r[1] in OPS and isinstance(r[2], (int, float, str))))
                if not ok:
                    raise ValueError(f"[{name}] {label}: bad rule {r!r}; expected [metric, op, value]")
    return rules


HEADER = """# YOUR rules. Every [section] is one advisor. Labels are checked top to bottom; the first label whose
# rules ALL pass is the verdict, otherwise `default`. Rule = [metric, op, value], op: < <= > >= == between.
# value: a number, another metric's name, or [low, high] for between. Edit here or on the Rules page.
"""


def dump_rules(rules):
    """dict -> TOML text. JSON arrays/strings of this shape are valid TOML, so json.dumps does the quoting."""
    key = lambda k: k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k)
    out = [HEADER]
    for name, section in rules.items():
        out.append(f"[{key(name)}]")
        out += [f"{key(label)} = {json.dumps(v)}" for label, v in section.items()]
        out.append("")
    return "\n".join(out)


def unknown_metrics(rules):
    """Metric names used in rules that no data source produces (typo, or an indicator period you removed)."""
    known = {m for group in metric_names(load_settings()).values() for m in group}
    used = {x for s in rules.values() for label, rs in s.items() if label != "default"
            for r in rs for x in (r[0], r[2]) if isinstance(x, str)}
    return sorted(used - known)


RULES = load_rules(RULES_FILE.read_text())
OWN_TAB = ("ipo", "mutual_fund")  # these judge IPOs / funds on their own tabs, not a stock


def check(rule, m):
    metric, op, val = rule
    x = m.get(metric)
    if op == "between":
        target = val
        ok = x is not None and val[0] <= x <= val[1]
    else:
        target = m.get(val) if isinstance(val, str) else val
        ok = x is not None and target is not None and OPS[op](x, target)
    return {"metric": metric, "op": op, "value": val, "actual": x, "target": target, "pass": ok}


def fmt(c):
    ref = f"{c['value']}({c['target']})" if isinstance(c["value"], str) else c["value"]
    return f"{'PASS' if c['pass'] else 'FAIL'} {c['metric']}={c['actual']} {c['op']} {ref}"


def verdict(section, m):
    """The first label whose rules all pass wins; otherwise the section's default label."""
    checks = {}
    for label, rules in section.items():
        if label == "default":
            continue
        checks[label] = [check(r, m) for r in rules]
        if all(c["pass"] for c in checks[label]):
            return {"verdict": label, "checks": checks}
    return {"verdict": section.get("default", "HOLD"), "checks": checks}


class State(TypedDict):
    symbol: str
    exchange: str
    use_llm: bool
    metrics: dict
    errors: dict
    verdicts: Annotated[dict, operator.or_]  # parallel agents each merge in {name: result}
    chain: list | None
    option_pick: dict | None
    report: str


def collect_node(s):
    metrics, errors, chain = collect(s["symbol"], s["exchange"])
    return {"metrics": metrics, "errors": errors, "chain": chain}


def option_pick_node(s):
    """Runs after every advisor: the side comes from the configured advisor's verdict."""
    if not s.get("chain"):
        return {"option_pick": None}
    cfg = load_settings()["option_pick"]
    v = s["verdicts"].get(cfg["advisor"], {}).get("verdict")
    m = s["metrics"]
    return {"option_pick": option_pick.pick(s["chain"], m["spot"], m["expiry"], v, cfg)}


def agent(name):
    return lambda s: {"verdicts": {name: verdict(RULES[name], s["metrics"])}}


SYSTEM = (
    "You write the summary for a rules-based verdict system for the Indian stock market (NSE/BSE). "
    "Each advisor's verdict was decided by the user's own rules and is final; never change or override it. "
    "For each advisor, explain the verdict in 1-2 lines using the actual metric values, and name the rules "
    "that were closest to flipping it. Then point out conflicts between advisors, missing data, and risk "
    "context (VIX, FII/DII flows, days to expiry, data timestamp). Metrics ending in _cr are in rupees crore "
    "(write e.g. ₹5,353 cr, never billions); _pct values are percent. Plain text, under 300 words."
)


def report_node(s):
    if not s["use_llm"]:
        return {"report": ""}
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return {"report": "(no summary: GROQ_API_KEY is not set)"}
    # Groq free tier: ~1000 requests/day, 8k tokens/min on this model. One run = one request.
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"metrics": s["metrics"], "data_errors": s["errors"], "verdicts": s["verdicts"],
                     "option_buy": s.get("option_pick") and {k: v for k, v in s["option_pick"].items() if k != "chain"}},
                    default=str)},
            ],
        },
        timeout=60,
    )
    if not r.ok:  # rate limit / bad key shouldn't hide the verdicts
        return {"report": f"(summary failed: Groq HTTP {r.status_code} {r.text[:200]})"}
    return {"report": r.json()["choices"][0]["message"]["content"]}


def build(names):
    g = StateGraph(State)
    g.add_node("collect", collect_node)
    g.add_node("option_pick", option_pick_node)
    g.add_node("report", report_node)
    g.add_edge(START, "collect")
    for n in names:
        g.add_node(n, agent(n))
        g.add_edge("collect", n)
        g.add_edge(n, "option_pick")  # waits for every advisor
    g.add_edge("option_pick", "report")
    g.add_edge("report", END)
    return g.compile()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console defaults to cp1252; LLM text has ₹, narrow spaces
    p = argparse.ArgumentParser()
    p.add_argument("symbol")
    p.add_argument("--exchange", default="NSE", choices=["NSE", "BSE"])
    p.add_argument("--only", help="comma-separated advisors, e.g. swing,options")
    p.add_argument("--no-llm", action="store_true", help="rules only, skip the LLM summary")
    a = p.parse_args()

    names = a.only.split(",") if a.only else list(RULES)
    out = build(names).invoke({"symbol": a.symbol.upper(), "exchange": a.exchange, "use_llm": not a.no_llm, "verdicts": {}})

    m = out["metrics"]
    print(f"\n{a.symbol.upper()} ({a.exchange})  price {m.get('price')} @ {m.get('price_time')}")
    for n in names:
        v = out["verdicts"][n]
        print(f"\n[{n}] -> {v['verdict']}")
        for label, checks in v["checks"].items():
            print(f"   {label}: " + " | ".join(map(fmt, checks)))
    if p := out.get("option_pick"):
        print(f"\n[option buy] {p['advisor']} says {p['verdict']} -> {p['signal'] or 'no signal'}  (expiry {p['expiry']})")
        for kind in ("CE", "PE"):
            x = p[kind]
            print(f"   best {kind}: " + (f"{x['strike']:g} {kind} @ {x['ltp']}  delta {x['delta']}  IV {x['iv']}  "
                                          f"OI {x['oi']}  spread {x['spread_pct']}%  breakeven {x['breakeven']}"
                                          if x else "no strike passes your liquidity filters"))
    if out["errors"]:
        print("\ndata errors:", out["errors"])
    if out["report"]:
        print("\n" + out["report"])
