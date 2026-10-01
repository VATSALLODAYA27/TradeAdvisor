"""Streamlit UI with the trading-terminal look. Verdicts only; nothing here places orders.

    .\\.venv\\Scripts\\streamlit.exe run app.py
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import advisor
import data
import history
import setups
import tabs
import views

st.set_page_config(page_title="Trade Advisor", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.html(views.CSS)

QUICK = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "HDFCBANK", "INFY", "SBIN"]
OPS = ["<", "<=", ">", ">=", "==", "between"]
fmt = views.fmt


def badge(label):
    return f'<span class="badge {views.tone(label)}">{views.e(str(label).replace("_", " "))}</span>'


@st.cache_data(ttl=120, show_spinner=False)
def get_candles(symbol, exchange, settings_key, vatsal_mode):  # settings_key busts the cache when settings change
    def one(iv):
        try:
            return iv, data.candles(symbol, exchange, iv, vatsal_mode)
        except Exception:
            return iv, None
    with ThreadPoolExecutor(4) as pool:  # the four timeframes download in parallel
        got = dict(pool.map(one, data.CHART))
    return {iv: c for iv, c in got.items() if c and c["time"]}


# Only the open tab runs (lazy tabs). Streamlit drops the state of widgets that didn't render this run, so the
# settings that must survive a tab switch are re-stored here first.
PERSIST = ("symbol", "exchange", "vatsal_mode", "advisors", "use_llm", "min_rr", "capital", "risk_pct", "opp_uni", "opp_dir",
           "opp_opts", "strat_preset", "strat_w", "strat_lots", "mkt_pick", "mkt_group", "sec_rel", "ev_fo", "brief_uni",
           "brief_rr", "brief_cap", "sc_strike", "sc_kind", "bt_sym", "bt_adv", "bt_period", "bt_exch", "bt_long", "bt_short",
           "bt_stop", "bt_target", "bt_cost", "bt_shorts")
for k in PERSIST:
    if k in st.session_state:
        st.session_state[k] = st.session_state[k]
if goto := st.session_state.pop("goto", None):  # another tab asked to open this one (e.g. "Open on Analyze tab")
    st.session_state.main_tab = goto


def left_tab():
    """Keep unsaved Rules edits: they live only in that tab's widgets, which vanish while another tab is open."""
    if "rules_live" in st.session_state:
        st.session_state.draft = st.session_state.pop("rules_live")
        st.session_state.ver = st.session_state.get("ver", 0) + 1  # fresh editor keys, rebuilt from the draft


topbar = st.empty()  # filled at the end, once this run's analysis (if any) is done
tab_an, tab_opp, tab_str, tab_bt, tab_mkt, tab_br, tab_jr, tab_rules, tab_ind = st.tabs(
    ["Analyze", "Opportunities", "Strategies", "Backtest", "Market", "Brief", "Journal", "Rules", "Indicators"],
    key="main_tab", on_change=left_tab)


# ---------- analyze ----------

st.session_state.setdefault("symbol", "RELIANCE")


def is_vatsal(name):
    return name.startswith("vatsal")


def vatsal_toggled():
    """Turning Vatsal's indicator on selects its advisors; turning it off removes them."""
    names = [n for n in advisor.RULES if is_vatsal(n)]
    cur = [a for a in st.session_state.get("advisors", []) if not is_vatsal(a)]
    st.session_state.advisors = cur + names if st.session_state.vatsal_mode else cur


def quick_pick():
    if st.session_state.quick:
        st.session_state.symbol = st.session_state.quick
        st.session_state.run = True
    st.session_state.quick = None


if tab_an.open:
    with tab_an:
        with st.container(key="controls"):
            c1, c2, c3 = st.columns([6, 1.4, 1.4], vertical_alignment="bottom")
            c1.text_input("Symbol", key="symbol", placeholder="Symbol, e.g. RELIANCE, or with a strike: NIFTY 22700 PE",
                          label_visibility="collapsed")
            exchange = c2.segmented_control("Exchange", ["NSE", "BSE"], default="NSE", key="exchange", label_visibility="collapsed") or "NSE"
            clicked = c3.button("Get verdict", type="primary", width="stretch")
            c1, c2 = st.columns([6, 1.6], vertical_alignment="center")
            vmode = c2.toggle("Vatsal's indicator", key="vatsal_mode", on_change=vatsal_toggled,
                              help="Your TradingView setup: EMA 5/13/50/200, EMA 200 filter, 50/200 cross, pivots, fib, "
                                   "supply/demand and liquidity zones, plus the vatsal advisors.")
            use_llm = c2.toggle("AI summary (Groq)", value=True, key="use_llm")
            names = [n for n in advisor.RULES if vmode or not is_vatsal(n)]
            if "advisors" in st.session_state:  # drop advisors deleted on the Rules tab or hidden by the toggle
                st.session_state.advisors = [a for a in st.session_state.advisors if a in names]
            chosen = c1.pills("Advisors", names, selection_mode="multi", default=names, key="advisors",
                              format_func=views.title, label_visibility="collapsed")
            st.pills("Quick pick", QUICK, key="quick", on_change=quick_pick, label_visibility="collapsed")

        if (clicked or st.session_state.pop("run", False)):
            sym, q_strike, q_kind = setups.parse_query(st.session_state.symbol)
            st.session_state.pending_strike = (sym, q_strike, q_kind or "CE") if q_strike else None
            if not chosen:
                st.error("Select at least one advisor.")
            else:
                with st.spinner(f"Fetching {sym} and running {len(chosen)} advisors…"):
                    out = advisor.build(chosen).invoke({"symbol": sym, "exchange": exchange, "use_llm": use_llm, "verdicts": {}})
                if "close" not in out["metrics"] and "price" not in out["metrics"]:
                    st.session_state.result = None
                    st.error(f'Couldn\'t find "{sym}" on {exchange}. Type an NSE symbol like RELIANCE or NIFTY, optionally with a '
                             f'strike and side, e.g. NIFTY 22700 PE. Details: {out["errors"]}')
                else:
                    st.session_state.result = out | {"order": chosen}
                    try:
                        history.record(out["symbol"], out["metrics"], out["verdicts"])  # one snapshot per symbol per day
                    except Exception:
                        pass

        result = st.session_state.get("result")
        if not result:
            st.html('<div class="empty">Pick a symbol and click <b>Get verdict</b>. Each advisor checks your rules against live NSE/BSE data.</div>')
        else:
            m = result["metrics"]
            st.html(views.quote(result))
            candles = get_candles(result["symbol"], result["exchange"], json.dumps(data.load_settings()), vmode)
            if candles:
                components.html(views.chart(candles, m), height=600)
            else:
                st.warning("Chart data unavailable right now.")
            if result["errors"]:
                st.html('<div class="alert">Some data was unavailable: ' + "".join(
                    f"<div><b>{views.e(k)}</b> — {views.e(v)}</div>" for k, v in result["errors"].items()) + "</div>")
            st.html(views.context_strip(m, history.iv_rank(result["symbol"], m.get("atm_iv"))))
            st.html(views.signals_panel(m))
            st.html('<div class="sec">Verdicts</div>' + views.verdicts(result))
            if vmode:
                st.html(views.vatsal_panel(m))
            if result.get("option_pick"):
                st.html(views.option_buy(result["option_pick"], m))

            # ---- trade setups: every setup from the levels in play, with option legs where a chain exists ----
            chain, opick = result.get("chain"), result.get("option_pick")
            pick_cfg = data.load_settings()["option_pick"]
            if m.get("atr"):
                found = setups.underlying_setups(m, m["atr"], vmode)
                bias = m.get("vs_bias") if vmode else (1 if m.get("close", 0) > m.get("ema_200", 0) else -1)
                items = [(x | {"verdict": setups.setup_verdict(x, bias)},
                          setups.option_legs(x, chain, m["spot"], m["expiry"], pick_cfg) if chain and m.get("expiry") else [])
                         for x in found]
                st.html(views.setups(items, bias, vmode))

            # ---- check any strike ----
            pending = st.session_state.get("pending_strike")
            if pending and pending[0] == result["symbol"] and not chain:
                st.warning(f"Couldn't check {pending[1]:g} {pending[2]}: the NSE option chain didn't load for {result['symbol']} "
                           "(it has no F&O contracts, or NSE refused the connection). Try Get verdict again.")
            if chain and m.get("expiry"):
                st.html('<div class="sec">Check a strike<span class="muted">study any CE/PE in this chain against your settings'
                        '</span></div>')
                strikes = sorted(r["strike"] for r in chain)
                gaps = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
                if st.session_state.get("sc_for") != result["symbol"]:  # new symbol: start the box at its ATM strike
                    st.session_state.sc_for = result["symbol"]
                    st.session_state.sc_strike = float(opick["atm"]) if opick else strikes[len(strikes) // 2]
                if pending and pending[0] == result["symbol"]:  # typed like "NIFTY 22700 PE": check it straight away
                    st.session_state.sc_strike, st.session_state.sc_kind = pending[1], pending[2]
                    st.session_state.strike_res = (result["symbol"], setups.check_strike(
                        chain, m["spot"], m["expiry"], pending[1], pending[2], m, result["verdicts"], pick_cfg, vatsal_mode=vmode))
                    st.session_state.pending_strike = None
                with st.form("strike_form", border=False), st.container(key="panel-strike"):
                    f1, f2, f3 = st.columns([2, 1.2, 1.2], vertical_alignment="bottom")
                    strike = f1.number_input("Strike", key="sc_strike", step=float(min(gaps)) if gaps else 1.0, format="%.2f")
                    kind = f2.segmented_control("Side", ["CE", "PE"], default="CE", key="sc_kind") or "CE"
                    go = f3.form_submit_button("Check strike", type="primary", width="stretch")
                if go:
                    st.session_state.strike_res = (result["symbol"], setups.check_strike(
                        chain, m["spot"], m["expiry"], float(strike), kind, m, result["verdicts"], pick_cfg, vatsal_mode=vmode))
                res = st.session_state.get("strike_res")
                if res and res[0] == result["symbol"]:
                    st.html(views.strike_check(res[1]))
            if result.get("report"):
                st.html(views.report(result["report"]))
            st.html(views.metrics(m))
            with st.expander(f"History for {result['symbol']} (saved daily)"):
                tabs.history_view(result["symbol"])
        st.caption("Tip: type a symbol with a strike to check that option straight away, e.g. NIFTY 22700 PE or RELIANCE 1200 CE.")
        st.html('<div class="footer">Verdicts come only from your rules. Nothing here places orders. Not investment advice.</div>')


# ---------- rules ----------

NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def to_text(v):
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)


def parse_value(op, text):
    text = (text or "").strip()
    if op == "between":
        parts = [x.strip() for x in text.split(",")]
        if len(parts) != 2 or not all(NUMBER.match(x) for x in parts):
            raise ValueError(f"'{text}': between needs 'low, high', e.g. 45, 65")
        return [float(x) if "." in x else int(x) for x in parts]
    if NUMBER.match(text):
        return float(text) if "." in text else int(text)
    if not text:
        raise ValueError("a value is empty")
    return text


def model_from(rules):
    return [{"name": n, "def": s.get("default", "HOLD"),
             "labels": [{"label": k, "rows": [[r[0], r[1], to_text(r[2])] for r in rs]} for k, rs in s.items() if k != "default"]}
            for n, s in rules.items()]


def rules_from(model):
    out = {}
    for a in model:
        name = a["name"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"advisor name '{name}': use letters, digits, _ or -")
        if name in out:
            raise ValueError(f"duplicate advisor '{name}'")
        section = {"default": a["def"].strip() or "HOLD"}
        for l in a["labels"]:
            label = l["label"].strip().upper().replace(" ", "_")
            if not label or label == "DEFAULT" or label in section:
                raise ValueError(f"[{name}] verdict name '{label}' is empty, reserved or duplicated")
            rows = [r for r in l["rows"] if any(x not in (None, "") for x in r)]
            if not rows:
                raise ValueError(f"[{name}] {label}: add at least one condition")
            section[label] = []
            for metric, op, value in rows:
                if not metric or op not in OPS:
                    raise ValueError(f"[{name}] {label}: every condition needs a metric and an operator")
                try:
                    section[label].append([metric.strip(), op, parse_value(op, value)])
                except ValueError as e:
                    raise ValueError(f"[{name}] {label} · {metric}: {e}")
        out[name] = section
    return out


def rules_tab(r):
    st.session_state.setdefault("ver", 0)
    if "draft" not in st.session_state:
        st.session_state.draft = model_from(advisor.RULES)
    draft, ver = st.session_state.draft, st.session_state.ver
    metrics = r["metrics"] if r else None
    known = [m for g in data.metric_names(data.load_settings()).values() for m in g]
    used = {row[0] for a in draft for l in a["labels"] for row in l["rows"] if row[0]}
    metric_options = known + sorted(used - set(known))

    head, toggle = st.columns([5, 1])
    head.markdown("Each advisor checks its verdicts **top to bottom**. When **every** condition under a verdict passes, that is "
                  "the verdict; otherwise it falls through to *If nothing matches*. "
                  + (f"The **now** line shows today's values for **{metrics['symbol']}**." if metrics
                     else "Run an analysis to see live ✓/✗ next to each condition."))
    as_toml = toggle.toggle("Edit as TOML")
    if unknown := advisor.unknown_metrics(advisor.RULES):
        st.warning(f"These metric names don't exist, so those conditions always fail: `{', '.join(unknown)}`. "
                   "Fix the spelling or add the period on the Indicators tab.")

    if as_toml:
        text = st.text_area("rules.toml", advisor.RULES_FILE.read_text(), height=520, label_visibility="collapsed")
        if st.button("Save TOML", type="primary"):
            try:
                advisor.RULES = advisor.load_rules(text)
                advisor.RULES_FILE.write_text(text)
                st.session_state.pop("draft", None)
                st.session_state.ver += 1
                st.success("Saved.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        return

    live, action = [], None
    for ai, a in enumerate(draft):
        with st.container(key=f"panel{ai}"):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 0.5], vertical_alignment="bottom")
            name = c1.text_input("Advisor", a["name"], key=f"{ver}:{ai}:name")
            dflt = c3.text_input("If nothing matches", a["def"], key=f"{ver}:{ai}:def")
            if c4.button("🗑", key=f"{ver}:{ai}:del", help=f"Delete advisor {a['name']}"):
                action = ("del_advisor", ai)
            labels = []
            for li, l in enumerate(a["labels"]):
                h1, h2, h3, h4 = st.columns([3, 0.4, 0.4, 0.4], vertical_alignment="bottom")
                label = h1.text_input("IF all pass →" if li == 0 else "ELSE IF all pass →", l["label"], key=f"{ver}:{ai}:{li}:label")
                if h2.button("↑", key=f"{ver}:{ai}:{li}:up", disabled=li == 0, help="Move up"):
                    action = ("move", ai, li, -1)
                if h3.button("↓", key=f"{ver}:{ai}:{li}:down", disabled=li == len(a["labels"]) - 1, help="Move down"):
                    action = ("move", ai, li, 1)
                if h4.button("✕", key=f"{ver}:{ai}:{li}:del", help=f"Delete verdict {l['label']}"):
                    action = ("del_label", ai, li)
                ed = st.data_editor(
                    pd.DataFrame(l["rows"], columns=["metric", "op", "value"]), key=f"{ver}:{ai}:{li}:rows",
                    num_rows="dynamic", hide_index=True, width="stretch",
                    column_config={
                        "metric": st.column_config.SelectboxColumn("Metric", options=metric_options, required=True, width="medium"),
                        "op": st.column_config.SelectboxColumn("Condition", options=OPS, required=True, width="small"),
                        "value": st.column_config.TextColumn("Value", required=True, width="medium",
                                                             help="A number, another metric's name (e.g. vwap), or 'low, high' for between"),
                    })
                rows = ed.astype(object).where(ed.notna(), None).values.tolist()
                if metrics and rows:
                    bits = []
                    for metric, op, value in rows:
                        try:
                            ok = advisor.check([metric, op, parse_value(op, value)], metrics)["pass"] if metric and op else None
                        except ValueError:
                            ok = None
                        bits.append(f"{'✅' if ok else '⭕' if ok is False else '·'} {metric} {fmt(metrics.get(metric))}")
                    st.caption("now: " + " · ".join(bits))
                labels.append({"label": label, "rows": rows})
            b1, b2, b3, _ = st.columns([1, 1, 1.2, 3])
            for col, (lab, text) in zip((b1, b2, b3), [("BUY", "+ BUY verdict"), ("SELL", "+ SELL verdict"), ("CUSTOM", "+ Custom verdict")]):
                if col.button(text, key=f"{ver}:{ai}:add{lab}"):
                    action = ("add_label", ai, lab)
            live.append({"name": name, "def": dflt, "labels": labels})
            try:
                preview = advisor.verdict(rules_from([live[-1]])[name.strip()], metrics)["verdict"] if metrics else None
            except ValueError:
                preview = None
            if preview:
                c2.html(f"<div style=\"padding-bottom:8px\">now → {badge(preview)}</div>")

    if st.button("+ Add advisor"):
        action = ("add_advisor",)

    if action:  # structural edits: apply to the live values, then redraw every widget fresh
        kind, *args = action
        if kind == "del_advisor":
            live.pop(args[0])
        elif kind == "move":
            ai, li, d = args
            L = live[ai]["labels"]
            L[li], L[li + d] = L[li + d], L[li]
        elif kind == "del_label":
            live[args[0]]["labels"].pop(args[1])
        elif kind == "add_label":
            ai, lab = args
            lab = f"VERDICT_{len(live[ai]['labels']) + 1}" if lab == "CUSTOM" else lab
            live[ai]["labels"].append({"label": lab, "rows": [["", ">", ""]]})
        elif kind == "add_advisor":
            live.append({"name": f"advisor_{len(live) + 1}", "def": "HOLD", "labels": [{"label": "BUY", "rows": [["", ">", ""]]}]})
        st.session_state.draft = live
        st.session_state.ver += 1
        st.rerun()

    st.session_state.rules_live = live
    dirty = live != model_from(advisor.RULES)
    s1, s2, msg = st.columns([1, 1, 4], vertical_alignment="center")
    if s1.button("Save rules", type="primary", disabled=not dirty):
        try:
            rules = rules_from(live)
            text = advisor.dump_rules(rules)
            advisor.RULES = advisor.load_rules(text)
            advisor.RULES_FILE.write_text(text)
            st.session_state.draft = model_from(advisor.RULES)
            st.session_state.ver += 1
            st.toast("Rules saved")
            st.rerun()
        except ValueError as e:
            msg.error(str(e))
    if s2.button("Discard", disabled=not dirty):
        st.session_state.draft = model_from(advisor.RULES)
        st.session_state.ver += 1
        st.rerun()
    if dirty:
        msg.caption("Unsaved changes")


if tab_rules.open:
    with tab_rules:
        rules_tab(st.session_state.get("result"))


# ---------- indicators ----------

def ints(text):
    try:
        return [int(x) for x in text.replace(" ", "").split(",") if x]
    except ValueError:
        return text  # validate_settings reports it


def indicators_tab():
    s = data.load_settings()
    st.markdown("These periods drive every metric, the rules and the chart. Metric names follow the settings: "
                "an EMA of 21 becomes `ema_21`.")
    with st.form("indicators"):
        c1, c2, c3, c4 = st.columns(4)
        ema = c1.text_input("EMA periods", ", ".join(map(str, s["ema"])), help="ema_<n>; the first 3 are drawn on the chart")
        sma = c2.text_input("SMA periods", ", ".join(map(str, s["sma"])), help="sma_<n>")
        rsi = c3.number_input("RSI period", 2, 400, s["rsi"], help="rsi, rsi_5m")
        atr = c4.number_input("ATR period", 2, 400, s["atr"], help="atr, atr_pct")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown("**MACD** · macd, macd_signal, macd_hist")
            m1, m2, m3 = st.columns(3)
            macd = [m1.number_input("Fast", 2, 400, s["macd"][0]), m2.number_input("Slow", 2, 400, s["macd"][1]),
                    m3.number_input("Signal", 2, 400, s["macd"][2])]
        with c2:
            st.markdown("**Bollinger** · bb_upper, bb_mid, bb_lower, bb_pct_b")
            b1, b2 = st.columns(2)
            boll = [b1.number_input("Period", 2, 400, s["bollinger"][0]), b2.number_input("Std dev ×", 0.1, 10.0, float(s["bollinger"][1]), 0.1)]
        with c3:
            st.markdown("**Supertrend** · supertrend, supertrend_dir")
            t1, t2 = st.columns(2)
            st_ = [t1.number_input("ATR period ", 2, 400, s["supertrend"][0]), t2.number_input("Multiplier", 0.1, 10.0, float(s["supertrend"][1]), 0.1)]
        with c4:
            st.markdown("**Volume & opening range**")
            vol = st.number_input("Volume average (days)", 2, 400, s["volume_avg"], help="vol_ratio")
            orb = st.selectbox("Opening range (min)", [5, 10, 15, 30, 45, 60], [5, 10, 15, 30, 45, 60].index(s["orb_minutes"]))

        st.markdown("#### Option buy")
        op = s["option_pick"]
        o1, o2, o3, o4, o5 = st.columns([1.2, 1.4, 1.4, 1, 1.4])
        advisors = list(dict.fromkeys([op["advisor"], *advisor.RULES]))
        adv = o1.selectbox("Side decided by advisor", advisors, advisors.index(op["advisor"]))
        ce_on = o2.text_input("Buy CE when verdict is", ", ".join(op["ce_on"]))
        pe_on = o3.text_input("Buy PE when verdict is", ", ".join(op["pe_on"]))
        delta = o4.number_input("Target delta", 0.05, 0.95, float(op["target_delta"]), 0.05,
                                help="0.5 ≈ ATM · 0.3 ≈ OTM (cheaper, needs a bigger move) · 0.7 ≈ ITM")
        p1, p2 = o5.columns(2)
        min_oi = p1.number_input("Min OI", 0, 10**8, op["min_oi"], 50, help="open interest, in contracts")
        spread = p2.number_input("Max spread %", 0.1, 50.0, float(op["max_spread_pct"]), 0.5)

        saved = st.form_submit_button("Save settings", type="primary")
    if saved:
        labels = lambda t: [x.strip().upper() for x in t.split(",") if x.strip()]
        new = {"ema": ints(ema), "sma": ints(sma), "rsi": rsi, "atr": atr, "macd": macd, "bollinger": boll, "supertrend": st_,
               "volume_avg": vol, "orb_minutes": orb,
               "option_pick": {"advisor": adv, "ce_on": labels(ce_on), "pe_on": labels(pe_on), "target_delta": delta,
                               "min_oi": min_oi, "max_spread_pct": spread}}
        try:
            clean = data.validate_settings(new)
            data.SETTINGS_FILE.write_text(json.dumps(clean, indent=2))
            if unknown := advisor.unknown_metrics(advisor.RULES):
                st.warning(f"Saved. Your rules still use `{', '.join(unknown)}`, which no longer exist. Update them on the Rules tab.")
            else:
                st.success("Saved. The next analysis uses these settings.")
        except ValueError as e:
            st.error(str(e))
    if s != data.DEFAULTS and st.button("Reset to defaults"):
        data.SETTINGS_FILE.unlink(missing_ok=True)
        st.rerun()


if tab_ind.open:
    with tab_ind:
        indicators_tab()


for tab, render in [(tab_opp, lambda: tabs.opportunities_tab(st.session_state.get("vatsal_mode", False))),
                    (tab_str, lambda: tabs.strategies_tab(st.session_state.get("result"))),
                    (tab_bt, lambda: tabs.backtest_tab(advisor.RULES, st.session_state.get("vatsal_mode", False))),
                    (tab_mkt, tabs.market_tab), (tab_br, tabs.brief_tab), (tab_jr, tabs.journal_tab)]:
    if tab.open:
        with tab:
            render()

with topbar:
    st.html(views.topbar((st.session_state.get("result") or {}).get("metrics")))
