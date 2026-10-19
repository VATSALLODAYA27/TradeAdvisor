"""AI Portfolio Desk: the SLM requirement document, as a standalone package.

It shares no code with the rest of TradeAdvisor. Its own pieces:
  indicators.py  RSI, EMA, SMA, ATR, Supertrend
  sources.py     NSE (Nifty 500 list, bhavcopy delivery %, filings), Yahoo prices and earnings, FRED macro, Google News
  engine.py      the Python quant engine: every number in FACTS
  rag.py         news, filings and earnings retrieval (BM25) for catalyst validation and red flags
  schema.py      the output schema as Pydantic models (Deliverable 3)
  model.py       the decision layer: gpt-oss-20b, schema-constrained decoding, validation and repair
  guard.py       guardrails: numbers only from FACTS, veto / bear / rebalance rules in code
  store.py       your inputs (desk.json) and the last result (desk_last.json, read by Taursa)
  dataset.py     financial instruction-tuning dataset with reasoning chains (Deliverable 2)
  finetune_colab.py  LoRA fine-tune of the base model on a free Colab GPU (not run on this PC)
  ui.py          the Streamlit tab
The only links out: the Streamlit tab registration, Taursa (its thinking animation plays while the desk runs) and the GROQ_API_KEY.
"""
from .pipeline import run  # noqa: F401
