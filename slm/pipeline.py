"""The flow from the PRD: quant engine → FACTS → SLM decision layer → schema-validated JSON → guardrails → dashboard."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from . import engine, guard, model, rag, sources, store

MACRO_SERIES = (("fed_funds_rate_pct", "FEDFUNDS"), ("us_10y_real_yield_pct", "DFII10"), ("us_10y_minus_2y_spread_pct", "T10Y2Y"))


def _try(fn, *a, default=None):
    try:
        return fn(*a)
    except Exception:
        return default


def macro(cfg, closes, reg):
    """2a. Macro scoring inputs: RBI / Fed rates, real yields, curve spread, CPI / WPI trend, correlations, trend momentum."""
    m = {"rbi_repo_rate_pct": cfg.get("repo_rate"), "india_wpi_trend": None}  # no free WPI feed: null, as rule 1 requires
    for k, sid in MACRO_SERIES:
        s = _try(sources.fred, sid)
        m[k], m[k.replace("_pct", "_date")] = (round(float(s.iloc[-1]), 2), s.index[-1].date().isoformat()) if s is not None else (None, None)
    cpi = _try(sources.fred, "INDCPIALLMINMEI")
    m |= engine.cpi_trend(cpi) if cpi is not None else {"india_cpi_yoy_pct": None, "india_cpi_trend": None}
    if m["rbi_repo_rate_pct"] is not None and m.get("india_cpi_yoy_pct") is not None:
        m["india_real_repo_rate_pct"] = round(m["rbi_repo_rate_pct"] - m["india_cpi_yoy_pct"], 2)
    return m | reg | {"asset_trend_momentum": engine.asset_trends(closes), "asset_correlations_1y": engine.correlations(closes)}


def facts(cfg, review_due=False, progress=None):
    say = progress or (lambda f, t: None)
    say(0.02, "Nifty 500 constituents from NSE")
    uni = sources.nifty500()
    industry, company = {u["symbol"]: u["industry"] for u in uni}, {u["symbol"]: u["company"] for u in uni}
    held = [p for p in cfg.get("positions") or [] if p.get("ticker")]
    names = list(dict.fromkeys([u["symbol"] for u in uni] + [p["ticker"] for p in held]))
    say(0.06, f"Two years of daily candles for {len(names)} stocks, the Nifty 500 and the asset ETFs")
    yt = [f"{t}.NS" for t in names] + list(dict.fromkeys(list(sources.ASSETS.values()) + sources.HEDGE))
    px = sources.candles(yt)
    say(0.55, "Features: RSI, Supertrend, SMAs, EMA bands, RS rank, sector strength")
    feats = {t: f for t in names if f"{t}.NS" in px and (f := _try(engine.features, px[f"{t}.NS"])) is not None}
    reg = engine.regime(px[sources.NIFTY500])
    bull = reg["nifty500_supertrend_weekly"] == 1
    universe = {t: f for t, f in feats.items() if t in industry}
    rs, sector_rel = engine.rs_and_sector(universe, industry)
    core, tact = engine.screens(universe, rs, sector_rel, industry, bull)
    say(0.65, "Delivery % from NSE bhavcopies")
    deliv = _try(sources.delivery)
    for group in (core, tact):
        engine.delivery_spikes(engine.size(group, cfg.get("stock_capital")), deliv)
    say(0.72, "News, NSE filings and earnings for the signals (RAG)")
    tickers = list(dict.fromkeys(s["ticker"] for s in core + tact))

    def evidence(t):
        news = _try(sources.headlines, company.get(t, t), default=[])
        fil = _try(sources.filings, t, default=[])
        earn = _try(sources.earnings, f"{t}.NS")
        return t, rag.retrieve(rag.documents(company.get(t, t), t, news, fil, earn), earn)
    with ThreadPoolExecutor(8) as pool:
        news = dict(pool.map(evidence, tickers))
    say(0.88, "Macro: FRED, CPI trend, asset correlations")
    closes = {k: px[v]["Close"] for k, v in sources.ASSETS.items() if v in px}
    last_px = {e: round(float(px[e]["Close"].iloc[-1]), 2) for e in sources.HEDGE if e in px}
    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "macro": macro(cfg, closes, reg),
        "breadth": engine.breadth(universe),
        "mf_allocation": engine.mf_allocation(cfg.get("funds") or {}, cfg.get("holdings") or {}, review_due),
        "weekly_core_signals": core, "daily_tactical_signals": tact,
        "exits": engine.exits(held, feats, bull),
        "news": news,
        "hedge": engine.hedge(bull, float(cfg.get("unallocated_cash") or 0), last_px),
        "compliance_disclaimer": guard.DISCLAIMER,
    }


def review_due(cfg, forced=False):
    """Annual review: forced from the tab, or the last review is a year old."""
    if forced:
        return True
    last = cfg.get("last_review")
    return bool(last) and (date.today() - date.fromisoformat(last)).days >= 365


def run(cfg, forced_review=False, use_model=True, progress=None):
    f = facts(cfg, review_due(cfg, forced_review) and any((cfg.get("holdings") or {}).values()), progress)
    (progress or (lambda *a: None))(0.93, f"{model.MODEL} is deciding")
    ans, err, meta = model.decide(f) if use_model else (None, "model turned off", {"model": None})
    out, fixes = guard.enforce(ans, f)
    result = {"facts": f, "model_answer": ans, "model_error": err, "model_meta": meta, "output": out, "fixes": fixes}
    store.save_last(result)
    return result
