"""Deliverable 1: evaluate the open-weights candidates and select the base model.

Each candidate answers the same held-out scenarios from dataset.py. Scored on what the PRD cares about:
  schema_valid   the answer passed the Pydantic schema (after Instructor's repair retries)
  rule_fixes     corrections the guardrails had to make (wrong conviction, wrong amount, invented ticker...): lower is better
  unverified     numbers in the prose that FACTS doesn't contain (arithmetic hallucination): lower is better
  seconds        latency per answer
Footprint is from the model cards: the selected model must fit a consumer GPU when self-hosted.

    .venv\\Scripts\\python.exe -m slm.evaluate 4      → slm/data/eval.json (runs on Groq; ~20 s pause between calls for the free tier)
"""
import json
import random
import sys
import time
from pathlib import Path

from . import dataset, guard, model

OUT = Path(__file__).with_name("data") / "eval.json"
FOOTPRINT = {  # from the model cards
    "openai/gpt-oss-20b": "21B total / 3.6B active (MoE), MXFP4: ~13 GB, fits one 16 GB consumer GPU",
    "qwen/qwen3.8-27b": "27B dense: ~16 GB at 4-bit, needs a 24 GB GPU",
    "openai/gpt-oss-120b": "117B / 5.1B active, MXFP4: ~63 GB, needs an 80 GB data-centre GPU (reference only)",
}


def run(n=4, seed=99, pause=20):
    rng = random.Random(seed)
    cases = [dataset.scenario(rng) for _ in range(n)]
    rows = []
    for m in model.CANDIDATES:
        scores = []
        for f in cases:
            ans, err, meta = model.decide(f, m)
            _, fixes = guard.enforce(ans, f)
            scores.append({"valid": ans is not None, "error": err, "fixes": len([x for x in fixes if "unverified" not in x]),
                           "unverified": len([x for x in fixes if "unverified" in x]), "seconds": meta.get("seconds"), "attempts": meta.get("attempts")})
            time.sleep(pause)
        ok = [s for s in scores if s["valid"]]
        rows.append({"model": m, "footprint": FOOTPRINT.get(m), "cases": n, "schema_valid": len(ok),
                     "avg_rule_fixes": round(sum(s["fixes"] for s in ok) / len(ok), 2) if ok else None,
                     "avg_unverified_numbers": round(sum(s["unverified"] for s in ok) / len(ok), 2) if ok else None,
                     "avg_seconds": round(sum(s["seconds"] or 0 for s in ok) / len(ok), 1) if ok else None,
                     "errors": sorted({s["error"] for s in scores if s["error"]})})
    fits = [r for r in rows if r["schema_valid"] and "consumer" in (r["footprint"] or "")]
    best = min(fits or rows, key=lambda r: (-(r["schema_valid"]), r["avg_rule_fixes"] or 99, r["avg_unverified_numbers"] or 99))
    res = {"run_at": time.strftime("%Y-%m-%d %H:%M"), "rows": rows, "selected": best["model"],
           "rule": "most schema-valid answers among models that fit a consumer GPU, then fewest guardrail fixes, then fewest unverified numbers"}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    return res


def view():
    import pandas as pd
    import streamlit as st
    st.caption("Deliverable 1 · base model selection. Every candidate is an open-weights model, run hosted on Groq (nothing runs on "
               "this PC), on the same held-out scenarios. Re-run with: .venv\\Scripts\\python.exe -m slm.evaluate 4")
    try:
        res = json.loads(OUT.read_text())
    except (FileNotFoundError, ValueError):
        st.info("No evaluation yet.")
        return
    st.markdown(f"**Selected: `{res['selected']}`** · {res['rule']} · run {res['run_at']}")
    st.dataframe(pd.DataFrame(res["rows"]), hide_index=True, width="stretch")


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else 4), indent=1))
