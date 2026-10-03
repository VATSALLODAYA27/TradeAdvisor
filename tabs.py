"""Streamlit tabs: Opportunities (scanner), Market (NSE scanners), Journal (your trades dashboard)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import advisor
import backtest
import brief
import history
import ipo
import journal
import market
import mf
import scanner
import strategies
from setups import years_to
from views import e, fmt, tone, verdicts

UP, DOWN, MUTED = "#16c784", "#ea3943", "#7d8aa5"
CHART_LAYOUT = dict(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,22,38,.6)",
                    margin=dict(l=8, r=8, t=30, b=8), font=dict(family="JetBrains Mono, Consolas"), height=320)


def _cards(best):
    out = []
    for _, r in best.iterrows():
        t = "t-up" if r["action"] == "BUY" else "t-down"
        qty = "" if pd.isna(r["qty"]) or r["qty"] is None else (
            f'<span>Qty</span><i>max loss ₹{fmt(r["max_loss"], 0)} · uses ₹{fmt(r["capital_used"], 0)}</i><b>{int(r["qty"])}</b>')
        out.append(
            f'<article class="panel card setup {t}"><header><span class="badge lg {t}">{r["action"]}</span>'
            f'<h3>{e(r["symbol"])} · {e(r["setup"])}</h3><span class="rr up">R:R {fmt(r["rr"])}</span></header>'
            f'<div class="plan"><span>When</span><i>{e(r["when"])}</i><b></b>'
            f'<span>Buy at</span><i>{"entry" if r["action"] == "BUY" else "sell (short) at"}</i><b>{fmt(r["entry"])}</b>'
            f'<span>Stop loss</span><i></i><b class="down">{fmt(r["stop"])}</b>'
            f'<span>Target</span><i></i><b class="up">{fmt(r["target"])}</b>{qty}</div>'
            f'<p class="note">{r["confirm"]}/4 confirmations ({e(r["agrees"])}) · price {fmt(r["price"])} '
            f'({r["change_pct"]:+.2f}%) · RSI {fmt(r["rsi"])} · signal score {int(r["sig_score"]):+d}</p></article>')
    return f'<div class="setups">{"".join(out)}</div>'


def opportunities_tab(vmode):
    st.html('<div class="sec">Opportunities<span class="muted">scan many shares for setups that meet YOUR reward:risk. '
            'Arithmetic on levels and signals, not predictions</span></div>')
    with st.container(key="panel-opp"):
        c1, c2, c3 = st.columns([1.4, 1, 1.2])
        uni = c1.selectbox("Universe", list(market.UNIVERSES), index=0, key="opp_uni")
        direction = c2.segmented_control("Direction", ["Both", "Long", "Short"], default="Both", key="opp_dir") or "Both"
        min_rr = c3.number_input("Your minimum reward:risk", 0.5, 10.0, st.session_state.get("min_rr", 2.0), 0.25, key="min_rr",
                                 help="Only setups whose target is at least this many times the risk are shown. 1:2 → enter 2.")
        c1, c2, c3, c4 = st.columns([1.4, 1, 1.2, 1], vertical_alignment="bottom")
        capital = c1.number_input("Capital ₹ (optional, for quantity)", 0, 10**10, st.session_state.get("capital", 0), 10000, key="capital")
        risk_pct = c2.number_input("Risk per trade %", 0.1, 10.0, 1.0, 0.1, key="risk_pct")
        opts = c3.toggle("Also pick options (top 5 F&O)", value=True, key="opp_opts")
        go_scan = c4.button("Scan", type="primary", width="stretch")
    status, note = scanner.market_status()
    st.html(f'<div class="osignal" style="margin:10px 0"><span class="badge {"t-up" if status == "open" else "t-warn"}">MARKET {status.upper()}</span>'
            f'<span class="muted">{e(note)}</span></div>')

    if go_scan:
        bar = st.progress(0.0, text="Downloading candles…")
        syms = market.universe(uni)
        df, failed = scanner.scan(syms, min_rr, capital or None, risk_pct, vmode, direction,
                                  progress=lambda f, s: bar.progress(f, text=f"Scanning {s}"))
        bar.progress(1.0, text="Picking options…" if opts else "Done")
        options = scanner.with_options(df.drop_duplicates("symbol"), market.universe("F&O stocks")) if opts and not df.empty else pd.DataFrame()
        bar.empty()
        st.session_state.opp = {"df": df, "options": options, "failed": failed, "universe": uni, "min_rr": min_rr, "n": len(syms)}

    res = st.session_state.get("opp")
    if not res:
        st.html('<div class="empty">Choose a universe and your minimum reward:risk, then click <b>Scan</b>.</div>')
        return
    df = res["df"]
    if df.empty:
        st.info(f"No setup in {res['universe']} meets reward:risk ≥ {res['min_rr']}. Try a lower ratio or another universe.")
        return
    best = df.drop_duplicates("symbol")
    st.html(f'<div class="sec">Top shares<span class="muted">{len(best)} of {res["n"]} in {e(res["universe"])} qualify · best plan per share · '
            f'sorted by confirmations then reward:risk</span></div>' + _cards(best.head(6)))
    if not res["options"].empty:
        st.html('<div class="sec">Options for the best F&amp;O names<span class="muted">ATM strike · CE for BUY, PE for SELL · '
                'premiums at stop/target are Black-Scholes estimates assuming the move happens today</span></div>')
        st.dataframe(res["options"], hide_index=True, width="stretch",
                     column_config={"buy_at": st.column_config.NumberColumn("Buy premium", format="%.2f"),
                                    "stop": st.column_config.NumberColumn("Stop premium", format="%.2f"),
                                    "target": st.column_config.NumberColumn("Target premium", format="%.2f")})

    st.html('<div class="sec">All qualifying setups<span class="muted">select rows, then add them to your journal or open one on '
            'the Analyze tab</span></div>')
    cols = ["symbol", "action", "setup", "when", "entry", "stop", "target", "target2", "rr", "confirm", "agrees", "qty",
            "max_loss", "price", "change_pct", "rsi", "sig_score", "why"]
    sel = st.dataframe(df[cols], hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key="opp_table",
                       column_config={"rr": st.column_config.NumberColumn("R:R", format="%.2f"),
                                      "confirm": st.column_config.ProgressColumn("Confirm", min_value=0, max_value=4, format="%d/4")})
    rows = sel.selection.rows if sel and sel.selection else []
    b1, b2, _ = st.columns([1.2, 1.2, 4])
    if b1.button(f"Add {len(rows)} to journal", disabled=not rows):
        for i in rows:
            r = df.iloc[i]
            journal.add(r["symbol"], r["action"], int(r["qty"]) if pd.notna(r["qty"]) and r["qty"] else 1, r["entry"],
                        r["stop"], r["target"], setup=r["setup"], notes=f"from scanner: {r['when']}")
        st.toast(f"Added {len(rows)} trade(s) to the journal")
    if b2.button("Open on Analyze tab", disabled=len(rows) != 1):
        st.session_state.symbol = df.iloc[rows[0]]["symbol"]
        st.session_state.run, st.session_state.goto = True, "Analyze"
        st.rerun()
    if res["failed"]:
        st.caption(f"No data for: {', '.join(res['failed'])}")


@st.cache_data(ttl=60, show_spinner=False)
def _scan(name, arg=None):
    fn = {"shockers": market.volume_shockers, "bought": market.most_bought, "value": lambda: market.most_active("value"),
          "volume": lambda: market.most_active("volume"), "gainers": lambda: market.movers("gainers", arg),
          "losers": lambda: market.movers("losers", arg), "oi": market.oi_spurts, "options": market.active_options}[name]
    return fn()


def market_tab():
    st.html('<div class="sec">Market scanners<span class="muted">live from NSE, refreshed every minute</span></div>')
    views = {"Sector heatmap": "sectors", "Events calendar": "events",
             "Volume shockers": "shockers", "Most bought (top value, price up)": "bought", "Most active by value": "value",
             "Most active by volume": "volume", "Top gainers": "gainers", "Top losers": "losers",
             "OI spurts (F&O)": "oi", "Most active options": "options"}
    c1, c2 = st.columns([4, 1.2])
    pick = c1.pills("Scanner", list(views), default="Sector heatmap", key="mkt_pick", label_visibility="collapsed") or "Sector heatmap"
    if views[pick] == "sectors":
        return sectors_view()
    if views[pick] == "events":
        return events_view()
    group = c2.selectbox("Group", list(market.MOVER_GROUPS), key="mkt_group", label_visibility="collapsed") if views[pick] in ("gainers", "losers") else None
    try:
        df = _scan(views[pick], group)
    except Exception as ex:
        st.warning(f"NSE didn't respond ({type(ex).__name__}). Try again in a moment.")
        return
    notes = {"shockers": "x_avg = today's volume ÷ the 1-week average volume.",
             "bought": "NSE doesn't publish buyer counts; this is the highest traded value among stocks that are up today.",
             "oi": "Biggest % jump in open interest across F&O underlyings today."}
    if views[pick] in notes:
        st.caption(notes[views[pick]])
    cfg = {"change_pct": st.column_config.NumberColumn("Change %", format="%+.2f"),
           "x_avg": st.column_config.NumberColumn("× avg volume", format="%.1f×"),
           "value_cr": st.column_config.NumberColumn("Value ₹cr", format="%,.1f"),
           "oi_change_pct": st.column_config.NumberColumn("OI change %", format="%+.2f")}
    sel = st.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1), 720), column_config=cfg,
                       on_select="rerun", selection_mode="single-row", key=f"mkt_{views[pick]}")
    if "symbol" in df and sel and sel.selection and sel.selection.rows:
        sym = df.iloc[sel.selection.rows[0]]["symbol"]
        if st.button(f"Analyze {sym}", type="primary"):
            st.session_state.symbol, st.session_state.run, st.session_state.goto = sym, True, "Analyze"
            st.rerun()
            st.rerun()


@st.cache_data(ttl=120, show_spinner=False)
def _sectors():
    return market.sectors()


def sectors_view():
    try:
        df, base = _sectors()
    except Exception as ex:
        st.warning(f"NSE didn't respond ({type(ex).__name__}). Try again in a moment.")
        return
    rel = st.toggle("Show strength relative to NIFTY 50 (sector return − NIFTY return)", key="sec_rel")
    cols = ["rs_1D", "rs_1W", "rs_1M", "rs_1Y"] if rel else ["1D", "1W", "1M", "1Y"]
    z = df[cols].astype(float)
    lim = max(1.0, float(z.abs().quantile(0.9).max()))  # symmetric colour scale, outliers clipped
    fig = go.Figure(go.Heatmap(
        z=z.values, x=["1 day", "1 week", "1 month", "1 year"], y=df["sector"], zmid=0, zmin=-lim, zmax=lim,
        colorscale=[[0, "#b4232f"], [0.5, "#1b2436"], [1, "#0e9f6e"]], xgap=2, ygap=2,
        text=[[f"{v:+.2f}%" if v == v else "—" for v in row] for row in z.values], texttemplate="%{text}",
        hovertemplate="%{y} · %{x}: %{text}<extra></extra>", colorbar=dict(title="%")))
    fig.update_layout(**{**CHART_LAYOUT, "height": 34 * len(df) + 80}, yaxis=dict(autorange="reversed"),
                      title=("Relative to NIFTY 50" if rel else "Sector returns") + f" · NIFTY today {base['1D']:+.2f}%, 1 month {base['1M']:+.2f}%")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.caption("Sorted by today's move. Green = stronger, red = weaker. Advancers/decliners per sector are in the table below.")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        c: st.column_config.NumberColumn(c, format="%+.2f") for c in ["1D", "1W", "1M", "1Y", "rs_1D", "rs_1W", "rs_1M", "rs_1Y"]})


def events_view():
    days = st.select_slider("Look ahead", [1, 3, 7, 14, 30], value=7, format_func=lambda d: f"{d} day{'s' if d > 1 else ''}")
    try:
        df = market.events(days)
    except Exception as ex:
        st.warning(f"NSE didn't respond ({type(ex).__name__}). Try again in a moment.")
        return
    fo = st.toggle("Only F&O stocks", value=True, key="ev_fo")
    if fo:
        try:
            df = df[df["symbol"].isin(market.universe("F&O stocks"))]
        except Exception:
            pass
    st.caption(f"{len(df)} events. Results can move a stock sharply and crush option IV afterwards; the strike check flags "
               "any event before expiry.")
    st.dataframe(df, hide_index=True, width="stretch", height=min(38 * (len(df) + 1), 720),
                 column_config={"when": st.column_config.DateColumn("Date"), "days_away": st.column_config.NumberColumn("In days")})


def history_view(symbol):
    df = history.series(symbol)
    if len(df) < 2:
        st.caption(f"History for {symbol} starts today: every analysis (and every morning brief) saves one snapshot per day, "
                   "so trends and IV rank appear after a few days.")
        return
    keys = [k for k in ("price", "atm_iv", "pcr_oi", "sig_score", "mtf_score", "rsi") if k in df and df[k].notna().any()]
    cols = st.columns(min(3, len(keys)))
    for i, k in enumerate(keys):
        fig = go.Figure(go.Scatter(x=df.index, y=df[k], mode="lines+markers", line=dict(color=UP if k != "atm_iv" else "#9b6bff", width=2)))
        fig.update_layout(**{**CHART_LAYOUT, "height": 220}, title=k)
        cols[i % len(cols)].plotly_chart(fig, width="stretch", config={"displaylogo": False})


def strategies_tab(result):
    st.html('<div class="sec">Option strategies<span class="muted">payoff at expiry and today, max profit/loss, breakevens, '
            'probability of profit · real NSE lot sizes</span></div>')
    chain = (result or {}).get("chain")
    if not chain:
        st.html('<div class="empty">Analyze an F&amp;O symbol first (e.g. NIFTY or RELIANCE) on the Analyze tab; '
                'strategies are built from its live option chain.</div>')
        return
    m = result["metrics"]
    sym, spot, expiry = result["symbol"], m["spot"], m["expiry"]
    lot = market.lot_size(sym) or 1
    rank = history.iv_rank(sym, m.get("atm_iv"))
    fit = strategies.fits(m, rank)
    with st.container(key="panel-strat"):
        c1, c2, c3 = st.columns([2, 1, 1])
        preset = c1.selectbox("Strategy", list(strategies.PRESETS),
                              format_func=lambda p: f"{p}  ✓ fits current signals" if p in fit else p, key="strat_preset")
        width = c2.number_input("Strikes away (OTM legs / spread width)", 1, 10, 2, key="strat_w")
        lots = c3.number_input(f"Lots (1 lot = {lot})", 1, 500, 1, key="strat_lots")
        st.caption(strategies.PRESETS[preset])
    legs = strategies.build(preset, chain, spot, width, lots)
    ed = st.data_editor(pd.DataFrame(legs), key=f"legs_{preset}_{width}_{lots}_{sym}", hide_index=True, width="stretch",
                        num_rows="dynamic", disabled=["premium", "iv"],
                        column_config={"side": st.column_config.SelectboxColumn("Buy (+1) / Sell (−1)", options=[1, -1]),
                                       "kind": st.column_config.SelectboxColumn("Type", options=["CE", "PE"]),
                                       "strike": st.column_config.NumberColumn("Strike", format="%.2f"),
                                       "premium": st.column_config.NumberColumn("Premium (live)", format="%.2f"),
                                       "iv": st.column_config.NumberColumn("IV %", format="%.2f"),
                                       "lots": st.column_config.NumberColumn("Lots", min_value=1)})
    # re-price every leg from the chain so edited strikes/types always carry the live premium
    legs = [strategies.leg(chain, int(r.side), r.kind, float(r.strike), int(r.lots))
            for r in ed.dropna(subset=["side", "kind", "strike", "lots"]).itertuples()]
    if not legs:
        return
    t = years_to(expiry)
    s = strategies.summary(legs, spot, lot, m.get("atm_iv"), t)
    money = lambda v: "Unlimited" if v is None else f"{'−' if v < 0 else ''}₹{fmt(abs(v), 0)}"
    kpis = [("Net premium", f"{'credit' if s['net_premium'] > 0 else 'debit'} ₹{fmt(abs(s['net_premium']), 0)}"),
            ("Max profit", money(s["max_profit"])), ("Max loss", money(s["max_loss"])),
            ("Breakevens", ", ".join(fmt(b) for b in s["breakevens"]) or "—"),
            ("Prob. of profit", "—" if s["pop"] is None else f"{s['pop']}%"),
            ("Reward:risk", "—" if s["reward_risk"] is None else fmt(s["reward_risk"])),
            ("IV rank", "building history" if rank is None else f"{rank}"), ("Expiry", f"{expiry} · lot {lot}")]
    st.html('<section class="panel"><div class="kpis" style="grid-template-columns:repeat(4,1fr)">' + "".join(
        f"<div><span>{k}</span><b>{v}</b></div>" for k, v in kpis) + "</div></section>")
    xs = strategies.grid(legs, spot)
    at_exp, today = strategies.payoff(legs, xs, lot), strategies.payoff(legs, xs, lot, t)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=[max(v, 0) for v in at_exp], fill="tozeroy", mode="none", fillcolor="rgba(22,199,132,.18)",
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=xs, y=[min(v, 0) for v in at_exp], fill="tozeroy", mode="none", fillcolor="rgba(234,57,67,.18)",
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=xs, y=at_exp, name="At expiry", line=dict(color="#e6ebf5", width=2)))
    fig.add_trace(go.Scatter(x=xs, y=today, name="Today (Black-Scholes)", line=dict(color="#3987e5", width=2, dash="dash")))
    fig.add_vline(x=spot, line_dash="dot", line_color=MUTED, annotation_text=f"spot {fmt(spot)}")
    for b in s["breakevens"]:
        fig.add_vline(x=b, line_dash="dot", line_color="#c98500", annotation_text=f"BE {fmt(b)}", annotation_position="bottom right")
    fig.add_hline(y=0, line_color=MUTED, line_width=1)
    fig.update_layout(**{**CHART_LAYOUT, "height": 420}, title=f"{sym} {preset} · P&L in ₹ vs price at expiry",
                      xaxis_title=f"{sym} price", yaxis_title="P&L ₹", legend=dict(orientation="h", y=-0.18), hovermode="x unified")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.caption("Premiums are last traded prices from NSE (you may fill at bid/ask). 'Today' re-prices each leg with its own IV "
               "and the time left; probability of profit is a risk-neutral estimate from ATM IV, not a forecast. Selling "
               "options needs margin and can lose more than the premium received.")


def backtest_tab(rules, vmode):
    st.html('<div class="sec">Backtest<span class="muted">replay one of your advisors over past daily candles · verdict at a close, '
            'fill at the next open · past results are not a forecast</span></div>')
    with st.container(key="panel-bt"):
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
        sym = c1.text_input("Symbol", st.session_state.get("symbol", "RELIANCE"), key="bt_sym").strip().upper()
        names = [n for n in rules if n not in advisor.OWN_TAB]
        name = c2.selectbox("Advisor (rules.toml section)", names, index=names.index("swing") if "swing" in names else 0, key="bt_adv")
        period = c3.selectbox("History", ["2y", "3y", "5y", "10y"], index=1, key="bt_period",
                              help="The first 200 candles only warm up the indicators; trades start after them.")
        exch = c4.selectbox("Exchange", ["NSE", "BSE"], key="bt_exch")
        labels = [k for k in rules[name] if k != "default"]
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 0.9, 0.9, 0.9, 1], vertical_alignment="bottom")
        long_l = c1.selectbox("Go long on", labels, index=labels.index("BUY") if "BUY" in labels else 0, key="bt_long")
        short_l = c2.selectbox("Exit long / go short on", labels, index=labels.index("SELL") if "SELL" in labels else min(1, len(labels) - 1), key="bt_short")
        stop = c3.number_input("Stop (×ATR, 0 = off)", 0.0, 20.0, 2.0, 0.5, key="bt_stop")
        target = c4.number_input("Target (×ATR, 0 = off)", 0.0, 50.0, 0.0, 0.5, key="bt_target")
        cost = c5.number_input("Cost % per side", 0.0, 2.0, 0.1, 0.05, key="bt_cost", help="Brokerage + STT + slippage, charged on entry and exit.")
        shorts = c6.toggle("Allow shorts", key="bt_shorts")
        go_bt = st.button("Run backtest", type="primary")
    if go_bt:
        bar = st.progress(0.0, text="Downloading candles…")
        try:
            st.session_state.bt = backtest.run(sym, rules[name], exch, period, vmode, lambda f, day: bar.progress(f, text=f"Replaying {day:%d %b %Y}"),
                                               long_label=long_l, short_label=short_l, shorts=shorts, stop_atr=stop, target_atr=target, cost_pct=cost)
            st.session_state.bt["title"] = f"{sym} · [{name}] {long_l} / {short_l}"
        except Exception as ex:
            st.session_state.bt = None
            st.warning(f"Backtest failed for {sym}: {ex}")
        bar.empty()
    r = st.session_state.get("bt")
    if not r:
        st.html('<div class="empty">Pick a symbol and one of your advisors, then click <b>Run backtest</b>. '
                'A 3-year run takes about 10–30 seconds.</div>')
        return
    if r["missing"]:
        st.warning(f"These metrics have no daily history, so rules using them never pass here: {', '.join(r['missing'])}. "
                   "Intraday, options, fundamentals and market metrics can't be backtested with free data.")
    s = r["stats"]
    pct = lambda v, sign=True: "—" if v is None else (f"{v:+.2f}%" if sign else f"{v:.1f}%")
    tone = lambda v: "" if v is None else ("up" if v > 0 else "down")
    kpis = [("Total return", pct(s["total_ret"]), tone(s["total_ret"])), ("Buy &amp; hold", pct(s["buy_hold"]), tone(s["buy_hold"])),
            ("CAGR", pct(s["cagr"]), tone(s["cagr"])), ("Max drawdown", pct(s["max_dd"]), "down"),
            ("Trades", s["trades"], ""), ("Win rate", pct(s["win_rate"], False), ""),
            ("Avg win / loss", f'{pct(s["avg_win"])} / {pct(s["avg_loss"])}', ""),
            ("Profit factor", "—" if s["profit_factor"] is None else fmt(s["profit_factor"]), ""),
            ("Time in market", pct(s["exposure"], False), "")]
    st.html('<section class="panel"><div class="kpis" style="grid-template-columns:repeat(3,1fr)">' + "".join(
        f'<div><span>{k}</span><b class="{c}">{v}</b></div>' for k, v, c in kpis) + "</div></section>")
    d, eq, tr = r["d"], r["equity"], r["trades"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq.index, y=(eq - 1) * 100, name="Strategy", line=dict(color=UP, width=2)))
    fig.add_trace(go.Scatter(x=d.index, y=(d["Close"] / d["Open"].iloc[0] - 1) * 100, name="Buy & hold", line=dict(color=MUTED, width=1.5, dash="dot")))
    fig.update_layout(**{**CHART_LAYOUT, "height": 360}, title=f"{r['title']} · return %", hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    if not tr.empty:
        fig2 = go.Figure(go.Scatter(x=d.index, y=d["Close"], name="Close", line=dict(color="#e6ebf5", width=1.2)))
        for side, col, sym_ in (("LONG", UP, "triangle-up"), ("SHORT", DOWN, "triangle-down")):
            t = tr[tr["side"] == side]
            fig2.add_trace(go.Scatter(x=t["entry_date"], y=t["entry"], mode="markers", name=f"{side} entry",
                                      marker=dict(color=col, symbol=sym_, size=10)))
        fig2.add_trace(go.Scatter(x=tr["exit_date"], y=tr["exit"], mode="markers", name="Exit",
                                  marker=dict(color="#c98500", symbol="x", size=8), hovertext=tr["exit_why"]))
        fig2.update_layout(**{**CHART_LAYOUT, "height": 360}, title="Entries and exits", legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig2, width="stretch", config={"displaylogo": False})
        st.dataframe(tr, hide_index=True, width="stretch",
                     column_config={"ret_pct": st.column_config.NumberColumn("Return %", format="%+.2f"),
                                    "entry_date": st.column_config.DateColumn("Entry date"), "exit_date": st.column_config.DateColumn("Exit date")})
    else:
        st.info("No trades: the long label never fired in this window. Check the verdict labels or try a longer history.")
    st.caption("Fully invested per trade, returns compound, costs on both sides. Stops/targets are checked on daily highs/lows; "
               "a gap through them fills at the open, and a day touching both counts as the stop.")


@st.cache_data(ttl=600, show_spinner=False)
def _ipos():
    return ipo.all_ipos()


def _x(v):
    return "—" if v is None else f"{v:,.2f}×"


@st.cache_data(ttl=1800, show_spinner=False)
def _listed(days):
    return ipo.listed(days)


def listed_view(kind):
    days = st.select_slider("Listed in the last", [30, 60, 90, 180, 365], value=90, key="ipo_days", format_func=lambda d: f"{d} days")
    try:
        with st.spinner("Fetching listings and prices…"):
            df = _listed(days)
    except Exception as ex:
        st.warning(f"NSE didn't respond ({type(ex).__name__}). Try again in a moment.")
        return
    if kind != "All" and not df.empty:
        df = df[df["type"] == kind]
    if df.empty:
        st.info("No listings in this window.")
        return
    priced = df.dropna(subset=["listing_gain_pct"])
    if len(priced):
        s = priced["listing_gain_pct"]
        kpis = [("IPOs listed", len(df), ""), ("Listed at a premium", f"{(s > 0).mean() * 100:.0f}%", ""),
                ("Avg listing gain", f"{s.mean():+.2f}%", "up" if s.mean() > 0 else "down"),
                ("Avg return since issue", f"{priced['return_pct'].mean():+.2f}%", "up" if priced["return_pct"].mean() > 0 else "down")]
        st.html('<section class="panel"><div class="kpis" style="grid-template-columns:repeat(4,1fr)">' + "".join(
            f'<div><span>{k}</span><b class="{c}">{v}</b></div>' for k, v, c in kpis) + "</div></section>")
        top = pd.concat([priced.nlargest(8, "return_pct"), priced.nsmallest(8, "return_pct")]).drop_duplicates("symbol")
        top = top.sort_values("return_pct")
        fig = go.Figure(go.Bar(x=top["return_pct"], y=top["company"], orientation="h",
                               marker_color=[UP if v > 0 else DOWN for v in top["return_pct"]],
                               text=[f"{v:+.1f}%" for v in top["return_pct"]], textposition="outside"))
        fig.update_layout(**{**CHART_LAYOUT, "height": 32 * len(top) + 90}, title="Best and worst: return from issue price to today")
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "listed": st.column_config.DateColumn("Listed"), "issue_price": st.column_config.NumberColumn("Issue ₹", format="%.0f"),
        "listing_open": st.column_config.NumberColumn("Listing open ₹", format="%.2f"),
        "listing_gain_pct": st.column_config.NumberColumn("Listing gain %", format="%+.2f"),
        "day1_close_pct": st.column_config.NumberColumn("Day-1 close %", format="%+.2f"),
        "price": st.column_config.NumberColumn("Now ₹", format="%.2f"), "return_pct": st.column_config.NumberColumn("Since issue %", format="%+.2f")})
    missing = df["price"].isna().sum()
    st.caption("Listing gain = listing-day open vs issue price. Prices from Yahoo"
               + (f"; {missing} listings (mostly SME) have no Yahoo data." if missing else "."))


def ipo_tab(rules):
    st.html('<div class="sec">IPOs<span class="muted">open and upcoming issues from NSE · GMP and financials from ipowatch.in · '
            'verdicts from the [ipo] section of your rules</span></div>')
    c0, c1, c2, _ = st.columns([2.2, 2.2, 1, 1.5], vertical_alignment="bottom")
    view = c0.segmented_control("View", ["Open & upcoming", "Recently listed"], default="Open & upcoming", key="ipo_view") or "Open & upcoming"
    kind = c1.segmented_control("Show", ["Mainboard", "SME", "All"], default="Mainboard", key="ipo_kind") or "Mainboard"
    if c2.button("Refresh", help="Data is cached for 10-30 minutes"):
        _ipos.clear()
        _listed.clear()
    if view == "Recently listed":
        return listed_view(kind)
    try:
        with st.spinner("Fetching IPOs, GMP and financials…"):
            xs = _ipos()
    except Exception as ex:
        st.warning(f"NSE didn't respond ({type(ex).__name__}). Try again in a moment.")
        return
    xs = [x for x in xs if kind == "All" or (x["row"].get("series") == "SME") == (kind == "SME")]
    if not xs:
        st.info(f"No open or upcoming {kind.lower()} IPOs on NSE right now.")
        return
    section = rules.get("ipo")
    if not section:
        st.info("Add an [ipo] section on the Rules tab (metrics start with ipo_) to get APPLY / AVOID verdicts here.")
    verdict = {id(x): advisor.verdict(section, x["metrics"]) if section else None for x in xs}

    df = pd.DataFrame([{
        "company": x["row"]["companyName"], "type": "SME" if x["row"].get("series") == "SME" else "Mainboard",
        "status": x["row"].get("status"), "opens": x["row"].get("issueStartDate"), "closes": x["row"].get("issueEndDate"),
        "price": x["metrics"]["ipo_price"], "min_invest": x["metrics"]["ipo_min_amount"],
        "gmp": x["metrics"]["ipo_gmp"], "gmp_pct": x["metrics"]["ipo_gmp_pct"],
        "sub_total": x["metrics"]["ipo_sub_total"], "sub_qib": x["metrics"]["ipo_sub_qib"],
        "sub_nii": x["metrics"]["ipo_sub_nii"], "sub_retail": x["metrics"]["ipo_sub_retail"],
        "verdict": verdict[id(x)]["verdict"] if verdict[id(x)] else "—"} for x in xs])
    times = lambda label: st.column_config.NumberColumn(label, format="%.2f×")
    sel = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="ipo_table",
                       column_config={"price": st.column_config.NumberColumn("Price ₹ (upper band)", format="%.0f"),
                                      "min_invest": st.column_config.NumberColumn("Min. retail ₹", format="%,.0f"),
                                      "gmp": st.column_config.NumberColumn("GMP ₹", format="%.0f"),
                                      "gmp_pct": st.column_config.NumberColumn("GMP %", format="%+.2f"),
                                      "sub_total": times("Subscribed"), "sub_qib": times("QIB"), "sub_nii": times("NII"),
                                      "sub_retail": times("Retail")})
    rows = sel.selection.rows if sel and sel.selection else []
    x = xs[rows[0]] if rows else xs[0]
    m, r, pg, v = x["metrics"], x["row"], x["page"], verdict[id(x)]
    st.caption("Select a row to see its details. Subscription keeps rising until the last day, so a verdict can change.")

    badge = f'<span class="badge lg {tone(v["verdict"])}">{e(v["verdict"].replace("_", " "))}</span>' if v else ""
    est = m["ipo_price"] + m["ipo_gmp"] if m["ipo_price"] and m["ipo_gmp"] is not None else None
    money = lambda val, d=0: "—" if val is None else f"₹{fmt(val, d)}"
    pct = lambda val: "—" if val is None else f"{val:+.2f}%"
    kpis = [("Price band", e(r.get("issuePrice") or r.get("priceBand") or "—")), ("Issue size", f"{money(m['ipo_issue_cr'], 2)} cr"),
            ("Min. retail investment", money(m["ipo_min_amount"])),
            ("GMP", f"{money(m['ipo_gmp'])} ({pct(m['ipo_gmp_pct'])})"), ("Est. listing price", money(est)),
            ("Subscribed (total)", _x(m["ipo_sub_total"])), ("Closes", f"{e(r.get('issueEndDate', '—'))} · {m['ipo_days_to_close']} days"),
            ("Promoters after IPO", "—" if m["ipo_promoter_post_pct"] is None else f"{fmt(m['ipo_promoter_post_pct'])}%"),
            ("Revenue (latest FY)", f"{money(m['ipo_revenue_cr'], 2)} cr · {pct(m['ipo_revenue_growth'])}"),
            ("Profit (latest FY)", f"{money(m['ipo_pat_cr'], 2)} cr · {pct(m['ipo_pat_growth'])}"),
            ("ROE / ROCE", f"{fmt(m['ipo_roe'])}% / {fmt(m['ipo_roce'])}%"),
            ("EBITDA / PAT margin", f"{fmt(m['ipo_ebitda_margin'])}% / {fmt(m['ipo_pat_margin'])}%"),
            ("Debt to equity", fmt(m["ipo_debt_equity"])), ("P/E at upper band", fmt(m["ipo_pe"]))]
    st.html(f'<section class="panel"><header style="display:flex;gap:12px;align-items:center;margin-bottom:10px">'
            f'<h3 style="margin:0">{e(r["companyName"])}</h3>{badge}</header>'
            f'<div class="kpis" style="grid-template-columns:repeat(4,1fr)">'
            + "".join(f"<div><span>{k}</span><b>{val}</b></div>" for k, val in kpis) + "</div></section>")

    c1, c2 = st.columns(2)
    cats = [(k, x["sub"].get(k.lower())) for k in ("QIB", "NII", "Retail", "Total")]
    if any(val is not None for _, val in cats):
        fig = go.Figure(go.Bar(x=[k for k, _ in cats], y=[val or 0 for _, val in cats], text=[_x(val) for _, val in cats],
                               textposition="outside", marker_color=[UP if (val or 0) >= 1 else MUTED for _, val in cats]))
        fig.add_hline(y=1, line_dash="dot", line_color=MUTED, annotation_text="fully subscribed")
        fig.update_layout(**CHART_LAYOUT, title=f"Subscription (times) · {x['sub'].get('updated') or ''}")
        c1.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    else:
        c1.info("Subscription starts when the issue opens." if r.get("status") != "Active" else "NSE has no bid data for this issue yet.")
    fin = pg.get("financials")
    if fin is not None:
        f = fin[fin.iloc[:, 0].astype(str).str.fullmatch(r"\s*(FY)?\s*\d{2,4}\s*")]
        fig = go.Figure()
        for col, color in (("Revenue", "#3987e5"), ("PAT", UP)):
            if col in f:
                fig.add_trace(go.Bar(x=f.iloc[:, 0].astype(str), y=f[col].map(ipo.num), name=col, marker_color=color))
        fig.update_layout(**CHART_LAYOUT, title="Revenue and profit by fiscal year (₹ crore)", barmode="group",
                          legend=dict(orientation="h", y=-0.15))
        c2.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    else:
        c2.info("No financials found for this IPO on ipowatch.in.")

    if v:
        st.html('<div class="sec">Your IPO rules</div>' + verdicts({"order": ["ipo"], "verdicts": {"ipo": v}}))
    for label, key in (("Financials", "financials"), ("Key ratios", "kpi"), ("Issue details", "issue"), ("Lot sizes", "lots"),
                       ("Timeline", "timeline"), ("Shareholding", "holding"), ("Objects of the issue", "objects")):
        if pg.get(key) is not None:
            with st.expander(label):
                st.dataframe(pg[key], hide_index=True, width="stretch")
    src = f' · <a href="{e(x["gmp"]["url"])}" target="_blank">ipowatch.in page</a>' if x["gmp"] and x["gmp"].get("url") else ""
    st.html(f'<p class="note">Sources: NSE (list, subscription){src}. GMP is an unofficial grey-market quote, not a listing '
            f'guarantee. Financials are from the prospectus as summarised by ipowatch.in; check the RHP before applying.</p>')
    if x["errors"]:
        st.caption("Unavailable: " + "; ".join(f"{k} ({val})" for k, val in x["errors"].items()))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _funds():
    return mf.funds()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _rank(category, plan, bench):
    f = _funds()
    return mf.rank(f[(f["category"] == category) & (f["plan"] == plan)], bench)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _nav(code):
    return mf.nav(code)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _bench(name):
    return mf.benchmark(name)


MF_SORT = {"3-year return": "mf_cagr_3y", "1-year return": "mf_ret_1y", "5-year return": "mf_cagr_5y",
           "Beat benchmark by (3y)": "mf_excess_3y", "Sharpe (3y)": "mf_sharpe_3y", "Lowest drawdown (3y)": "mf_max_dd_3y"}
MF_COLS = {"mf_ret_1y": "1y %", "mf_cagr_3y": "3y CAGR %", "mf_cagr_5y": "5y CAGR %", "mf_excess_3y": "vs bench 3y (pp)",
           "mf_sharpe_3y": "Sharpe", "mf_sortino_3y": "Sortino", "mf_vol_3y": "Volatility %", "mf_max_dd_3y": "Max drawdown %",
           "mf_beta_3y": "Beta", "mf_alpha_3y": "Alpha %", "mf_age_years": "Age (yrs)"}


def _mf_table(rows, section):
    out = []
    for r in rows:
        v = advisor.verdict(section, r["metrics"])["verdict"] if section else "—"
        out.append({"fund": r["name"], "verdict": v, **{MF_COLS[k]: r["metrics"][k] for k in MF_COLS}})
    return pd.DataFrame(out).astype({c: float for c in MF_COLS.values()})


def _cat_changed():
    st.session_state.mf_bench = mf.default_benchmark(st.session_state.mf_cat)


def mf_tab(rules):
    st.html('<div class="sec">Mutual funds<span class="muted">every scheme from AMFI · NAV history from mfapi.in · '
            'rank a category, compare funds with benchmarks · verdicts from the [mutual_fund] section of your rules</span></div>')
    try:
        with st.spinner("Loading the AMFI scheme list…"):
            funds = _funds()
    except Exception as ex:
        st.warning(f"AMFI didn't respond ({type(ex).__name__}). Try again in a moment.")
        return
    section = rules.get("mutual_fund")
    cats = sorted(funds["category"].unique())
    st.session_state.setdefault("mf_cat", "Equity · Flexi Cap" if "Equity · Flexi Cap" in cats else cats[0])
    st.session_state.setdefault("mf_bench", mf.default_benchmark(st.session_state.mf_cat))
    with st.container(key="panel-mf"):
        c1, c2, c3, c4 = st.columns([2.2, 1.2, 2, 1.6], vertical_alignment="bottom")
        cat = c1.selectbox("Category", cats, key="mf_cat", on_change=_cat_changed)
        plan = c2.segmented_control("Plan", ["Direct", "Regular"], default="Direct", key="mf_plan") or "Direct"
        bench = c3.selectbox("Benchmark", list(mf.BENCHMARKS), key="mf_bench",
                             help="Price indices exclude dividends, so funds look ~1-1.5%/yr better than against the TRI on their factsheets.")
        sort = c4.selectbox("Rank by", list(MF_SORT), key="mf_sort")
    pool = funds[(funds["category"] == cat) & (funds["plan"] == plan)]
    key, top = (cat, plan, bench), []
    done = st.session_state.setdefault("mf_ranked", [])
    if key not in done:
        secs = max(5, len(pool) * 0.7)
        if st.button(f"Rank {len(pool)} {plan.lower()} funds in {cat} (about {secs:.0f}s the first time, then cached for 6 hours)", type="primary"):
            done.append(key)
            st.rerun()
        st.html('<div class="empty">Pick a category and click <b>Rank</b>: every fund is measured from its NAV history '
                'against the benchmark, then judged by your [mutual_fund] rules.</div>')
    else:
        with st.spinner(f"Ranking {len(pool)} funds…"):
            rows = _rank(cat, plan, bench)
        col = MF_SORT[sort]
        rows = [r for r in rows if r["metrics"][col] is not None]
        rows.sort(key=lambda r: r["metrics"][col], reverse=True)
        if not rows:
            st.info(f"No fund in {cat} has enough history for '{sort}'. Try a shorter period.")
        else:
            bench_val = {"mf_ret_1y": 1, "mf_cagr_3y": 3, "mf_cagr_5y": 5}.get(col)
            b = mf.cagr(_bench(bench), bench_val) if bench_val else None
            best, worst = rows[:5], rows[-5:][::-1] if len(rows) > 5 else []
            show = best + [r for r in worst if r not in best]
            show = sorted(show, key=lambda r: r["metrics"][col])
            top = [r["name"] for r in rows[:3]]
            if st.session_state.get("mf_cmp_for") != key:  # a fresh ranking: compare its leaders, not the old picks
                st.session_state.mf_cmp, st.session_state.mf_cmp_for = top, key
            fig = go.Figure(go.Bar(x=[r["metrics"][col] for r in show], y=[r["name"][:48] for r in show], orientation="h",
                                   marker_color=[UP if r in best else DOWN for r in show],
                                   text=[f"{r['metrics'][col]:.2f}" for r in show], textposition="outside"))
            if b is not None:
                fig.add_vline(x=b, line_dash="dot", line_color=MUTED, annotation_text=f"{bench} {b:.2f}%")
            fig.update_layout(**{**CHART_LAYOUT, "height": 34 * len(show) + 90},
                              title=f"Top 5 and bottom 5 of {len(rows)} by {sort.lower()}")
            st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
            df = _mf_table(rows, section)
            pct = {c: st.column_config.NumberColumn(c, format="%.2f") for c in MF_COLS.values()}
            st.dataframe(df, hide_index=True, width="stretch", column_config=pct, height=min(38 * (len(df) + 1), 560))
            counts = df["verdict"].value_counts().to_dict()
            st.caption(f"Sorted by {sort.lower()}. Verdicts: " + ", ".join(f"{k} {v}" for k, v in counts.items())
                       + ". pp = percentage points above the benchmark's return over the same 3 years.")

    st.html('<div class="sec">Compare<span class="muted">growth of ₹10,000 from the latest date all picks existed · '
            'any funds, any categories, plus benchmarks</span></div>')
    names = funds[funds["plan"] == plan].drop_duplicates("name").set_index("name")["code"]
    in_cat = [n for n in pool["name"] if n in names.index]
    c1, c2, c3 = st.columns([3, 2, 1.4], vertical_alignment="bottom")
    picks = c1.multiselect("Funds (up to 5)", list(names.index), default=(top or in_cat)[:3], max_selections=5, key="mf_cmp")
    benches = c2.multiselect("Benchmarks", list(mf.BENCHMARKS), default=[bench], key="mf_cmp_bench")
    period = c3.segmented_control("Period", ["1Y", "3Y", "5Y", "Max"], default="3Y", key="mf_period") or "3Y"
    if not picks and not benches:
        return
    try:
        with st.spinner("Fetching NAV history…"):
            series = {n: _nav(int(names[n])) for n in picks} | {f"▸ {b}": _bench(b) for b in benches}
    except Exception as ex:
        st.warning(f"Couldn't fetch NAV history ({type(ex).__name__}).")
        return
    g = mf.growth(series, None if period == "Max" else int(period[0]))
    fig = go.Figure()
    for i, (n, s) in enumerate(g.items()):
        is_b = n.startswith("▸")
        fig.add_trace(go.Scatter(x=s.index, y=s, name=n[:50], line=dict(width=1.5 if is_b else 2.2, dash="dot" if is_b else "solid")))
    start = min(s.index[0] for s in g.values())
    youngest = max(series, key=lambda n: series[n].index[0])
    if period != "Max" and series[youngest].index[0] > max(s.index[-1] for s in g.values()) - pd.DateOffset(years=int(period[0])):
        st.caption(f"The chart starts {start:%d %b %Y}, when {youngest} began, so every line is measured over the same days.")
    fig.update_layout(**{**CHART_LAYOUT, "height": 420}, title=f"Growth of ₹10,000 since {start:%d %b %Y}", hovermode="x unified",
                      legend=dict(orientation="h", y=-0.2), yaxis_title="₹")
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False})
    b0 = _bench(bench)
    rows = [{"name": n, "metrics": mf.metrics(series[n], b0)} for n in picks]
    if rows:
        st.dataframe(_mf_table(rows, section), hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(c, format="%.2f") for c in MF_COLS.values()})
    st.caption(f"Metrics are vs {bench}. Past returns don't predict future returns. Expense ratio, AUM and holdings are not "
               "in these free sources; check the factsheet before investing.")


def brief_tab():
    st.html('<div class="sec">Morning brief<span class="muted">market mood, sectors, events, top setups at your reward:risk and '
            'your open trades · best run before 09:15</span></div>')
    with st.container(key="panel-brief"):
        c1, c2, c3, c4 = st.columns([1.4, 1, 1.2, 1], vertical_alignment="bottom")
        uni = c1.selectbox("Universe", list(market.UNIVERSES), key="brief_uni")
        rr = c2.number_input("Min reward:risk", 0.5, 10.0, st.session_state.get("min_rr", 2.0), 0.25, key="brief_rr")
        cap = c3.number_input("Capital ₹ (optional)", 0, 10**10, st.session_state.get("capital", 0), 10000, key="brief_cap")
        go_b = c4.button("Generate brief", type="primary", width="stretch")
    if go_b:
        with st.spinner("Building the brief…"):
            b = brief.build(rr, uni, cap or None, st.session_state.get("risk_pct", 1.0), st.session_state.get("vatsal_mode", False))
            path = brief.to_pdf(b, brief.OUT_DIR / f"brief_{b['generated']:%Y-%m-%d}.pdf")
        st.session_state.brief = (b, path)
    got = st.session_state.get("brief")
    if not got:
        st.html('<div class="empty">Click <b>Generate brief</b>. It also saves a PDF in the <b>briefs</b> folder.</div>')
        return
    b, path = got
    st.html(f'<section class="panel"><b>{b["generated"]:%A %d %B, %H:%M}</b><p class="note" style="font-size:13px;color:#e6ebf5">'
            f'{e(b["mood"])}</p></section>')
    st.download_button("Download PDF", path.read_bytes(), path.name, "application/pdf")
    if b.get("scan") is not None and not b["scan"].empty:
        st.html(f'<div class="sec">Top setups<span class="muted">{e(b["universe"])} · reward:risk ≥ {b["min_rr"]}</span></div>'
                + _cards(b["scan"].drop_duplicates("symbol").head(6)))
    if b.get("trades") is not None and not b["trades"].empty:
        st.html('<div class="sec">Your open trades</div>')
        st.dataframe(b["trades"], hide_index=True, width="stretch")
    if b.get("events") is not None and not b["events"].empty:
        st.html('<div class="sec">Corporate events today and tomorrow</div>')
        st.dataframe(b["events"], hide_index=True, width="stretch")
    if b["errors"]:
        st.caption("Unavailable: " + "; ".join(f"{k} ({v})" for k, v in b["errors"].items()))


def journal_tab():
    df = journal.load()
    s = journal.stats(df)
    st.html('<div class="sec">Trade journal<span class="muted">saved in trades.csv next to the app · open it in Excel any time</span></div>')
    if s["trades"]:
        kpis = [("Closed trades", s["trades"], ""), ("Open", s["open"], ""),
                ("Total P&amp;L", f"₹{fmt(s['total_pnl'], 0)}", "up" if s["total_pnl"] > 0 else "down"),
                ("Win rate", f"{fmt(s['win_rate'], 1)}%", ""), ("Avg win / loss", f"₹{fmt(s['avg_win'], 0)} / ₹{fmt(s['avg_loss'], 0)}", ""),
                ("Profit factor", fmt(s["profit_factor"]), ""), ("Avg R", fmt(s["avg_r"]), ""),
                ("Max drawdown", f"₹{fmt(s['max_drawdown'], 0)}", "down")]
        st.html('<section class="panel"><div class="kpis" style="grid-template-columns:repeat(4,1fr)">' + "".join(
            f'<div><span>{k}</span><b class="{c}">{v}</b></div>' for k, v, c in kpis) + "</div></section>")
        c1, c2 = st.columns([1.6, 1])
        cv = s["curve"]
        fig = go.Figure(go.Scatter(x=list(range(1, len(cv) + 1)), y=cv["equity"], mode="lines+markers", line=dict(color=UP, width=2),
                                   hovertext=[f"{d} · trade ₹{p:,.0f}" for d, p in zip(cv["exit_date"], cv["pnl"])]))
        fig.update_layout(title="Equity curve (cumulative ₹ P&L by closed trade)", xaxis_title="trade #", **CHART_LAYOUT)
        c1.plotly_chart(fig, width="stretch", config={"displaylogo": False})
        bs = s["by_symbol"]
        fig2 = go.Figure(go.Bar(x=bs.values, y=bs.index, orientation="h", marker_color=[UP if v > 0 else DOWN for v in bs.values]))
        fig2.update_layout(title="P&L by symbol", **CHART_LAYOUT)
        c2.plotly_chart(fig2, width="stretch", config={"displaylogo": False})
    else:
        st.html(f'<div class="empty">No closed trades yet ({s["open"]} open). Add trades below or from the Opportunities tab; '
                'fill in <b>exit</b> when you close one and the dashboard fills in.</div>')

    with st.form("add_trade", border=False), st.container(key="panel-add"):
        st.markdown("**Add a trade**")
        c = st.columns([1.3, 1.6, 0.9, 0.8, 1, 1, 1, 1.1])
        sym = c[0].text_input("Symbol")
        inst = c[1].text_input("Instrument", "Stock", help="Stock, or e.g. NIFTY 22700 PE 06-Oct")
        side = c[2].selectbox("Side", ["BUY", "SELL"])
        qty = c[3].number_input("Qty", 1, 10**7, 1)
        entry = c[4].number_input("Entry", 0.0, 10**7 * 1.0, 0.0, 0.05, format="%.2f")
        stop = c[5].number_input("Stop", 0.0, 10**7 * 1.0, 0.0, 0.05, format="%.2f")
        target = c[6].number_input("Target", 0.0, 10**7 * 1.0, 0.0, 0.05, format="%.2f")
        if c[7].form_submit_button("Add", type="primary", width="stretch"):
            if not sym.strip() or entry <= 0:
                st.error("Symbol and entry are required.")
            else:
                journal.add(sym.strip().upper(), side, qty, entry, stop or None, target or None, inst or "Stock")
                st.rerun()

    st.markdown("**All trades**: edit any cell (e.g. type the exit price and date to close a trade), then save.")
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="journal_editor",
                        column_config={"side": st.column_config.SelectboxColumn(options=["BUY", "SELL"]),
                                       "status": st.column_config.SelectboxColumn(options=["OPEN", "CLOSED"]),
                                       "date": st.column_config.DateColumn(), "exit_date": st.column_config.DateColumn()})
    if st.button("Save journal", type="primary", disabled=ed.equals(df)):
        journal.save(ed)
        st.toast("Journal saved")
        st.rerun()
    if s["trades"]:
        st.download_button("Download trades.csv", journal.FILE.read_bytes() if journal.FILE.exists() else b"", "trades.csv", "text/csv")
        with st.expander("By setup type"):
            st.dataframe(s["by_setup"].rename(columns={"count": "trades", "sum": "P&L ₹"}), width="stretch")
