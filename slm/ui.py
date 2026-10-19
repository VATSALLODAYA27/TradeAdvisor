"""The AI Portfolio Desk tab. Streamlit only; the bull-and-bear animation is Taursa's thinking indicator."""
import json
from datetime import date

import pandas as pd
import streamlit as st

from . import engine, evaluate, model, pipeline, store

TONE = {"High": "t-up", "Moderate": "t-warn", "Veto": "t-down", "Bullish": "t-up", "Bearish": "t-down", "Neutral": "t-flat"}
esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
num = lambda v, d=2: "—" if v is None else f"{v:,.{d}f}"
pct = lambda v: "—" if v is None else f"{v}%"


def _kpis(items, cols=4):
    st.html(f'<section class="panel"><div class="kpis" style="grid-template-columns:repeat({cols},1fr)">' + "".join(
        f'<div><span>{k}</span><b class="{c}">{v}</b></div>' for k, v, c in items) + "</div></section>")


def _inputs():
    cfg = store.load()
    with st.expander("Your portfolio & macro inputs", expanded=not any((cfg.get("holdings") or {}).values())):
        with st.form("desk_cfg", border=False):
            st.markdown("**Mutual-fund sleeves** · current value of each fund (targets 35 / 25 / 25 / 15, Direct Plan, Growth)")
            funds, hold = {}, {}
            for s, tgt, default, _ in engine.SLEEVES:
                c1, c2 = st.columns([3, 1.2])
                funds[s] = c1.text_input(f"{s} fund · target {tgt}%", cfg["funds"].get(s) or default)
                hold[s] = c2.number_input(f"{s} value ₹", 0.0, 1e12, float(cfg["holdings"].get(s) or 0), 1000.0, format="%.0f")
            st.markdown("**Direct equity sleeve**")
            c1, c2, c3, c4 = st.columns(4)
            cap = c1.number_input("Stock capital ₹ (10 equal positions)", 0.0, 1e12, float(cfg.get("stock_capital") or 0), 10000.0, format="%.0f")
            cash = c2.number_input("Unallocated cash ₹ (hedge in a bear regime)", 0.0, 1e12, float(cfg.get("unallocated_cash") or 0), 10000.0, format="%.0f")
            repo = c3.number_input("RBI repo rate % (0 = unknown)", 0.0, 20.0, float(cfg.get("repo_rate") or 0), 0.05)
            last = c4.date_input("Last annual review", date.fromisoformat(cfg["last_review"]) if cfg.get("last_review") else None)
            st.caption("Stocks you hold from these models (for exits): ticker, sleeve, entry price, quantity.")
            pos = st.data_editor(pd.DataFrame(cfg.get("positions") or [], columns=["ticker", "sleeve", "entry_price", "quantity"]),
                                 num_rows="dynamic", hide_index=True, width="stretch", column_config={
                                     "sleeve": st.column_config.SelectboxColumn(options=["Weekly Core", "Daily Tactical"], required=True),
                                     "entry_price": st.column_config.NumberColumn(min_value=0.01), "quantity": st.column_config.NumberColumn(min_value=1)})
            if st.form_submit_button("Save inputs", type="primary"):
                rows = [{k: (str(v).strip().upper() if k == "ticker" else v) for k, v in r.items()}
                        for r in pos.astype(object).where(pos.notna(), None).to_dict("records") if r.get("ticker")]
                store.save(cfg | {"funds": funds, "holdings": hold, "stock_capital": cap, "unallocated_cash": cash, "repo_rate": repo or None,
                                  "last_review": last.isoformat() if last else None, "positions": rows})
                st.toast("Inputs saved")
                st.rerun()
    return cfg


def _cards(rows, facts):
    sig = {(s["ticker"], sl): s for sl, k in (("Weekly Core", "weekly_core_signals"), ("Daily Tactical", "daily_tactical_signals")) for s in facts[k]}
    out = []
    for d in rows:
        s, t = sig.get((d["ticker"], d["strategy_sleeve"]), {}), TONE[d["conviction"]]
        size = f'<span>Qty<b>{s.get("quantity") or "—"}</b></span><span>Position<b>₹{num(s.get("position_inr"), 0)}</b></span>' if s.get("position_inr") else ""
        out.append(
            f'<article class="panel card {t}"><header><h3>{esc(d["ticker"])} <span class="muted" style="font-size:12px">{esc(d["strategy_sleeve"])}'
            f' · {esc(s.get("industry") or "")}</span></h3><span class="badge {t}">{esc(d["conviction"])}</span></header>'
            f'<div class="levels" style="gap:12px"><span>Entry<b>{num(d["entry_price"])}</b></span><span>Stop<b class="down">{num(d["stop_loss_price"])}</b></span>'
            f'{size}<span>RS<b>{s.get("rs_percentile")}</b></span><span>vs sector<b>{pct(s.get("sector_relative_6m_pct"))}</b></span>'
            f'<span>Delivery<b>{pct(s.get("delivery_pct"))}{" ↑" if s.get("delivery_spike") else ""}</b></span></div>'
            f'<p style="margin:8px 0 4px"><b>Technical:</b> {esc(d["technical_rationale"])}</p>'
            f'<p style="margin:4px 0"><b>Catalyst:</b> {esc(d["fundamental_catalyst"])}</p>'
            f'<p style="margin:4px 0" class="muted"><b>Risks:</b> {esc(d["downside_risks"])}</p>'
            f'<p class="muted" style="margin:4px 0;font-size:11px">{esc(s.get("execution") or "")} · {esc(s.get("stop_rule") or "")}</p></article>')
    return f'<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(330px,1fr))">{"".join(out)}</div>'


def _results(r):
    f, o = r["facts"], r["output"]
    mv, mac = o["macro_verdict"], f["macro"]
    t = TONE[mv["regime"]]
    st.html(f'<section class="panel card {t}"><header><h3>Macro verdict</h3><span class="badge {t}">{esc(mv["regime"])}</span></header>'
            f'<p><b>Breadth:</b> {esc(mv["breadth_summary"])}</p><p>{esc(mv["rationale"])}</p></section>')
    _kpis([("Nifty 500", num(mac.get("nifty500_close")), ""),
           ("Supertrend weekly / daily", f'{mac.get("nifty500_supertrend_weekly")} / {mac.get("nifty500_supertrend_daily")}',
            "up" if mac.get("nifty500_supertrend_weekly") == 1 else "down"),
           ("Above 50 / 200-day SMA", f'{pct(f["breadth"].get("pct_above_sma50"))} / {pct(f["breadth"].get("pct_above_sma200"))}', ""),
           ("RBI repo / real", f'{pct(mac.get("rbi_repo_rate_pct"))} / {pct(mac.get("india_real_repo_rate_pct"))}', ""),
           ("India CPI YoY", f'{pct(mac.get("india_cpi_yoy_pct"))} ({mac.get("india_cpi_trend") or "—"}, {mac.get("india_cpi_date") or "—"})', ""),
           ("Fed funds", pct(mac.get("fed_funds_rate_pct")), ""), ("US 10y real yield", pct(mac.get("us_10y_real_yield_pct")), ""),
           ("US 10y − 2y", pct(mac.get("us_10y_minus_2y_spread_pct")), "")])
    with st.expander("Asset-class trend momentum and correlations"):
        c1, c2 = st.columns(2)
        c1.dataframe(pd.DataFrame(mac.get("asset_trend_momentum") or {}).T, width="stretch")
        c2.dataframe(pd.Series(mac.get("asset_correlations_1y") or {}, name="1-year weekly correlation"), width="stretch")
    h = f["hedge"]
    if h["active"]:
        st.html('<div class="alert"><b>Downside hedge active.</b> ' + esc(h["note"]) + ": " + " · ".join(
            f'{x["etf"]} ₹{num(x["amount_inr"], 0)} ({x["units"] or "—"} units at ₹{num(x["price"])})' for x in h["orders"]) + "</div>")

    st.html('<div class="sec">Mutual-fund rebalance<span class="muted">annual review, ±5% drift trigger · amounts from the engine</span></div>')
    alloc = {x["fund_name"]: x for x in f["mf_allocation"]["funds"]}
    st.dataframe(pd.DataFrame([{"fund": m["fund_name"], "target %": alloc[m["fund_name"]]["target_pct"], "current %": alloc[m["fund_name"]]["current_pct"],
                                "drift %": alloc[m["fund_name"]]["drift_pct"], "action": m["action"], "amount ₹": m["amount_inr"], "reason": m["reason"]}
                               for m in o["mutual_fund_rebalance_orders"]]), hide_index=True, width="stretch")

    st.html(f'<div class="sec">Dual-momentum stock decisions<span class="muted">Weekly Core Defense ({len(f["weekly_core_signals"])}) · '
            f'Daily Tactical &amp; Hedged ({len(f["daily_tactical_signals"])}) · Nifty 500</span></div>')
    if o["stock_trade_decisions"]:
        st.html(_cards(o["stock_trade_decisions"], f))
    else:
        st.info("No Nifty 500 stock passed either screen today.")
    with st.expander("News & catalyst evidence retrieved for each signal (RAG)"):
        for tkr, n in f["news"].items():
            st.markdown(f"**{tkr}** · {n['documents_searched']} documents searched · earnings: "
                        + (f"{n['earnings_surprise']['surprise_pct']}% surprise ({n['earnings_surprise']['date']})" if n.get("earnings_surprise") else "—"))
            for kind in ("red_flags", "supportive"):
                for x in n[kind]:
                    st.markdown(f"- {'🚩' if kind == 'red_flags' else '✅'} {x}")
            for x in n["catalyst_passages"] + n["risk_passages"]:
                st.caption(f"{x['source']} · {x['date']} · score {x['score']}: {x['text'][:160]}")
    st.html('<div class="sec">Portfolio exits<span class="muted">your desk positions that hit an exit rule</span></div>')
    if o["portfolio_exits"]:
        st.dataframe(pd.DataFrame(f["exits"]), hide_index=True, width="stretch")
    else:
        st.caption("No exits. Add the stocks you hold from these models under the inputs to have them checked.")
    st.html(f'<div class="alert"><b>Compliance disclaimer.</b> {esc(o["compliance_disclaimer"])}</div>')
    meta = r.get("model_meta") or {}
    with st.expander(f"Guardrails · {len(r['fixes'])} correction(s) · model: "
                     + (f"{meta.get('model')} answered in {meta.get('seconds')} s, {meta.get('attempts')} attempt(s)" if r["model_answer"] else f"not used ({r['model_error']})")):
        st.caption(f"Schema: {meta.get('schema', '—')}. Every change the guardrails made to the model's answer:")
        for x in r["fixes"] or ["No corrections needed."]:
            st.markdown(f"- {x}")
    c1, c2 = st.columns(2)
    with c1.expander("FACTS sent to the model"):
        st.json(f, expanded=False)
    with c2.expander("Model's raw answer"):
        st.json(r["model_answer"] or {}, expanded=False)
    st.download_button("Download decision JSON", json.dumps(o, indent=2, ensure_ascii=False), f"desk_{f['as_of'][:10]}.json", "application/json")


def render(thinking):
    """thinking: Taursa's animation context manager (tabs.thinking)."""
    st.html('<div class="sec">AI Portfolio Desk<span class="muted">quant engine computes every number · small open-weights model '
            f'({model.MODEL}) decides and explains · schema and rule guardrails · not investment advice</span></div>')
    desk, ev = st.tabs(["Desk", "Model evaluation"], key="desk_view", on_change="rerun")
    if ev.open:
        with ev:
            evaluate.view()
    if not desk.open:
        return
    with desk:
        cfg = _inputs()
        c1, c2, c3 = st.columns([1.3, 1.6, 3], vertical_alignment="center")
        use_model = c2.toggle("Use the AI model", True, key="desk_model", help="Off: the same output from the rules alone")
        forced = c3.checkbox("Run the annual review now", key="desk_review",
                             help="Rebalance every sleeve to target even inside ±5% drift. Also automatic a year after the last review.")
        if c1.button("Run the desk", type="primary", width="stretch"):
            words = ["Nifty 500", "Supertrend", "RSI 14", "RS rank", "breadth", "delivery %", "NSE filings", "earnings", "RBI", "Fed", "CPI",
                     model.MODEL.split("/")[-1]]
            with thinking(words, "Starting…") as show:
                try:
                    st.session_state.desk = pipeline.run(cfg, forced, use_model, lambda fr, txt: show(f"{int(fr * 100)}% · {txt}"))
                except Exception as ex:
                    st.session_state.desk = None
                    st.error(f"The desk couldn't finish: {type(ex).__name__}: {ex}")
        r = st.session_state.get("desk") or store.last()
        if not r:
            st.html('<div class="empty">Enter your inputs above, then <b>Run the desk</b>. It scans all Nifty 500 stocks, so a run takes '
                    'one to two minutes.</div>')
            return
        st.caption(f"Result from {r['facts']['as_of']}")
        _results(r)
