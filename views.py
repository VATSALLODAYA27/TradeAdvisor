"""HTML/CSS for the Streamlit UI: the trading-terminal look of the old React app. Pure string builders, no Streamlit calls."""
import html
import json
import re

import signals as sigmod

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
:root {
  --bg: #070b14; --bg-2: #0b1220; --panel: rgba(15, 22, 38, 0.82); --panel-2: #131c2f;
  --line: #1e2a42; --line-2: #2a3a58; --text: #e6ebf5; --muted: #7d8aa5;
  --up: #16c784; --up-bg: rgba(22, 199, 132, 0.12); --down: #ea3943; --down-bg: rgba(234, 57, 67, 0.12);
  --warn: #f0b90b; --warn-bg: rgba(240, 185, 11, 0.12); --accent: #3b82f6;
  --mono: 'JetBrains Mono', ui-monospace, Consolas, monospace;
}
/* ---- page + Streamlit chrome ---- */
.stApp { background-color: var(--bg); font-family: Inter, system-ui, 'Segoe UI', sans-serif;
  background-image: radial-gradient(1200px 600px at 85% -10%, rgba(22,199,132,.10), transparent 60%),
    radial-gradient(900px 500px at -10% 10%, rgba(59,130,246,.12), transparent 60%),
    linear-gradient(rgba(59,130,246,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(59,130,246,.05) 1px, transparent 1px);
  background-size: auto, auto, 40px 40px, 40px 40px; background-attachment: fixed; }
header[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display: none; }
.block-container, [data-testid="stMainBlockContainer"] { max-width: 1320px; padding: 12px 16px 40px; }
h1, h2, h3, h4 { font-family: Inter, system-ui, sans-serif; }
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); font-weight: 400; }
.up { color: var(--up); } .down { color: var(--down); }

/* widgets */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-baseweb="select"] > div, textarea {
  background: var(--bg-2) !important; border-color: var(--line-2) !important; font-family: var(--mono); }
[data-testid="stTextInput"] input { letter-spacing: .04em; }
button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(180deg, #1fd894, var(--up)) !important; color: #04110b !important; border: 0 !important; font-weight: 600; }
/* chips (st.pills, keyed) */
.st-key-advisors button, .st-key-quick button { font-size: 12px; border-radius: 999px; background: var(--bg-2) !important;
  border: 1px solid var(--line-2) !important; color: var(--muted) !important; }
.st-key-advisors button[aria-checked="true"], .st-key-advisors button[aria-pressed="true"] { background: rgba(59,130,246,.14) !important; border-color: var(--accent) !important; color: var(--text) !important; }
.st-key-quick button { font-family: var(--mono); border-radius: 6px; border-color: var(--line) !important; }
.st-key-quick button:hover { color: var(--text) !important; border-color: var(--line-2) !important; }
.st-key-quick { border-top: 1px dashed var(--line); padding-top: 10px; }
/* NSE/BSE segmented */
.st-key-exchange button { background: var(--bg-2) !important; color: var(--muted) !important; font-weight: 600; border-color: var(--line-2) !important; }
.st-key-exchange button[aria-checked="true"], .st-key-exchange button[aria-pressed="true"] { background: var(--accent) !important; color: #fff !important; border-color: var(--accent) !important; }
/* bordered containers / forms read as panels */
.st-key-controls, [class*="st-key-panel"], div[data-testid="stForm"] {
  background: var(--panel); border: 1px solid var(--line) !important; border-radius: 12px; padding: 16px; }
/* tabs as a segmented nav */
[data-testid="stTabs"] [role="tablist"] { gap: 2px; background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px; padding: 3px; width: fit-content; }
[data-testid="stTab"] { padding: 6px 16px !important; border-radius: 6px; color: var(--muted); height: auto; }
[data-testid="stTab"][aria-selected="true"] { background: var(--panel-2); color: var(--text); box-shadow: inset 0 0 0 1px var(--line-2); }
[data-testid="stTabs"] .react-aria-SelectionIndicator { display: none; }
[data-testid="stTabs"] [role="tablist"] + div, [data-testid="stTabs"] hr { border: 0 !important; }
[data-testid="stAlert"] { border-radius: 8px; }

/* ---- top bar ---- */
.topbar { display: flex; align-items: center; gap: 22px; padding: 10px 0 12px; margin-bottom: 10px; border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 700; letter-spacing: .08em; white-space: nowrap; color: var(--text); }
.logo { width: 26px; height: 26px; background: var(--bg-2) no-repeat center / 20px
  url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cpath d='M5 22l7-7 5 4 10-11' fill='none' stroke='%2316c784' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  border: 1px solid var(--line-2); border-radius: 7px; }
.brand b { color: var(--up); }
.brand em { font-style: normal; font-size: 11px; color: var(--muted); border: 1px solid var(--line-2); border-radius: 4px; padding: 1px 6px; }
.strip { display: flex; gap: 22px; flex: 1; overflow-x: auto; scrollbar-width: none; }
.tick { display: flex; align-items: baseline; gap: 6px; white-space: nowrap; font-size: 12px; color: var(--text); }
.tick span { color: var(--muted); font-size: 11px; letter-spacing: .04em; }
.tick b { font-weight: 600; font-family: var(--mono); }
.tick i { font-style: normal; font-size: 11px; font-family: var(--mono); }

/* ---- panels & headings ---- */
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px; color: var(--text); }
.sec { font-size: 13px; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin: 26px 0 12px; font-weight: 600; }
.sec .muted { text-transform: none; letter-spacing: 0; font-size: 12px; margin-left: 8px; }
.empty { margin: 48px 0; text-align: center; color: var(--muted); }
.alert { padding: 10px 14px; border-radius: 8px; background: var(--warn-bg); border: 1px solid rgba(240,185,11,.3); color: #f5d77a; font-size: 13px; margin-top: 12px; }

/* ---- quote header ---- */
.quote { display: grid; grid-template-columns: 1.2fr 1fr 1.3fr; gap: 24px; align-items: center; margin-top: 4px; }
.sym { font-size: 20px; font-weight: 700; letter-spacing: .03em; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tag { font-size: 11px; font-weight: 500; color: var(--muted); border: 1px solid var(--line-2); border-radius: 4px; padding: 1px 6px; }
.px { display: flex; align-items: baseline; gap: 12px; margin: 4px 0; }
.big { font-size: 32px; font-weight: 600; }
.chg { font-size: 15px; font-weight: 600; padding: 2px 8px; border-radius: 6px; }
.chg.up { background: var(--up-bg); } .chg.down { background: var(--down-bg); }
.asof { font-size: 12px; }
.ranges { display: grid; gap: 14px; }
.range .muted { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.bar { position: relative; height: 6px; border-radius: 99px; margin: 6px 0 4px; background: linear-gradient(90deg, var(--down), var(--warn) 50%, var(--up)); opacity: .8; }
.bar i { position: absolute; top: -4px; width: 4px; height: 14px; margin-left: -2px; background: #fff; border-radius: 2px; box-shadow: 0 0 0 2px var(--bg); }
.ends { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }
.kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.kpis div { background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.kpis span { display: block; font-size: 11px; color: var(--muted); }
.kpis b { font-size: 15px; font-weight: 600; font-family: var(--mono); }

/* ---- verdict cards ---- */
.t-up { --tone: var(--up); --tone-bg: var(--up-bg); }
.t-down { --tone: var(--down); --tone-bg: var(--down-bg); }
.t-warn { --tone: var(--warn); --tone-bg: var(--warn-bg); }
.t-flat { --tone: var(--muted); --tone-bg: var(--panel-2); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.card { position: relative; overflow: hidden; }
.card::before { content: ''; position: absolute; inset: 0 0 auto 0; height: 3px; background: var(--tone); }
.card.t-flat::before { background: var(--line-2); }
.card > header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card h3 { margin: 0; font-size: 15px; font-weight: 600; padding: 0; }
.badge { font-family: var(--mono); font-size: 12px; font-weight: 700; letter-spacing: .06em; padding: 4px 10px; border-radius: 6px;
  color: var(--tone); background: var(--tone-bg); border: 1px solid color-mix(in srgb, var(--tone) 40%, transparent); white-space: nowrap; }
.badge.lg { font-size: 14px; padding: 6px 14px; }
.group { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin-top: 8px; background: rgba(7,11,20,.4); }
.group.won { border-color: var(--line-2); background: var(--panel-2); }
.ghead { display: flex; align-items: center; gap: 10px; font-size: 12px; }
.lbl { font-weight: 700; letter-spacing: .04em; font-size: 11px; min-width: 64px; color: var(--tone); font-family: var(--mono); }
.meter { flex: 1; height: 4px; background: var(--line); border-radius: 99px; overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--accent); }
.group ul { list-style: none; margin: 6px 0 0; padding: 0; display: grid; gap: 3px; }
.group li { display: grid; grid-template-columns: 10px minmax(0,1fr) minmax(0,1.25fr) auto; gap: 8px; align-items: center; font-size: 12px; margin: 0; }
.group li > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.pass .dot { background: var(--up); box-shadow: 0 0 6px rgba(22,199,132,.6); }
.fail .dot { border: 1.5px solid var(--down); }
.fail .metric { color: var(--muted); }
.cond { color: #aab4c8; }
.actual { text-align: right; font-weight: 600; min-width: 56px; }
.pass .actual { color: var(--up); }

/* ---- option buy ---- */
.obuy { display: grid; gap: 14px; }
.osignal { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 12px; }
.olegs { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.oleg { border: 1px solid var(--line); border-radius: 10px; padding: 14px; background: rgba(7,11,20,.4); }
.oleg.active { border-color: var(--tone); box-shadow: 0 0 0 1px var(--tone), 0 0 24px color-mix(in srgb, var(--tone) 18%, transparent); background: var(--tone-bg); }
.oleg.dim { opacity: .5; }
.olabel { display: flex; align-items: center; gap: 8px; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.olabel .badge { font-size: 10px; padding: 1px 6px; }
.ostrike { font-size: 26px; font-weight: 700; margin-top: 4px; font-family: var(--mono); }
.ostrike span { color: var(--tone); font-size: 18px; }
.oprem { font-size: 16px; font-weight: 600; margin-bottom: 10px; font-family: var(--mono); }
.oprem .muted { font-size: 12px; font-family: Inter, sans-serif; }
.oleg dl { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 0; }
.oleg dl div { background: var(--bg-2); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; min-width: 0; }
.oleg dt { font-size: 10px; color: var(--muted); }
.oleg dd { margin: 0; font-size: 12px; font-weight: 600; font-family: var(--mono); overflow-wrap: anywhere; }
.levels { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12px; color: var(--muted); padding: 10px 12px; border: 1px dashed var(--line-2); border-radius: 8px; font-family: var(--mono); }
.levels b { color: var(--text); margin-left: 4px; }
.levels b.up { color: var(--up); } .levels b.down { color: var(--down); }
.ochain { overflow-x: auto; }
.ochain table { font-size: 12px; min-width: 720px; width: 100%; border-collapse: collapse; font-family: var(--mono); }
.ochain th { font-weight: 600; font-size: 11px; padding: 4px 6px; text-align: right; color: var(--muted); border: 0; }
.ochain th.hc { text-align: center; letter-spacing: .1em; }
.ochain td { text-align: right; padding: 4px 6px; border: 0; border-bottom: 1px solid var(--line); color: var(--text); }
.ochain td.strike { text-align: center; font-weight: 700; background: var(--bg-2); }
.ochain tr.atm td { border-top: 1px solid var(--accent); border-bottom-color: var(--accent); }
.ochain tr.atm td.strike { color: var(--accent); }
.ochain td.itm { background: rgba(240,185,11,.05); }
.ochain td.pick { background: rgba(59,130,246,.12); }
.ochain td.pick.active { background: rgba(59,130,246,.28); }
.ochain td.ltp { font-weight: 600; }
.ochain td.oi { position: relative; min-width: 90px; }
.ochain td.oi i { position: absolute; top: 4px; bottom: 4px; opacity: .25; border-radius: 2px; }
.ochain td.oi i.ce { right: 6px; background: var(--down); }
.ochain td.oi i.pe { left: 6px; background: var(--up); }
.ochain td.oi span { position: relative; }
.ochain td.oi.pe, .ochain th.pe-oi { text-align: left; }
.foot { margin: 0; font-size: 12px; }

/* ---- report + metrics ---- */
.report p { margin: 0 0 6px; line-height: 1.6; font-size: 14px; }
.report hr { border: 0; border-top: 1px solid var(--line); margin: 12px 0; }
.metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.metrics h4 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); padding: 0; }
.metrics table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: var(--mono); }
.metrics td { padding: 4px 0; border: 0; border-bottom: 1px solid var(--line); color: var(--text); }
.metrics td:first-child { color: var(--muted); }
.metrics td:last-child { text-align: right; }
.metrics tr:last-child td { border-bottom: 0; }
.footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; text-align: center; }

@media (max-width: 980px) { .quote { grid-template-columns: 1fr; } .topbar { flex-wrap: wrap; } .strip { flex-basis: 100%; } }
@media (max-width: 720px) { .olegs { grid-template-columns: 1fr; } .oleg dl { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .grid { grid-template-columns: 1fr; } .kpis { grid-template-columns: repeat(2, 1fr); } .big { font-size: 26px; } }
/* ---- signals ---- */
.sigs { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.sigs h4 { margin: 0 0 8px; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; padding: 0; }
.sigs ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.sigs li { display: flex; gap: 8px; align-items: center; font-size: 12.5px; color: var(--muted); margin: 0; }
.sigs li.on { color: var(--text); font-weight: 500; }
.sigs li i { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--line-2); flex: none; }
.sigs .bull li.on i { background: var(--up); border-color: var(--up); box-shadow: 0 0 6px rgba(22,199,132,.6); }
.sigs .bear li.on i { background: var(--down); border-color: var(--down); box-shadow: 0 0 6px rgba(234,57,67,.6); }
.meterbar { display: flex; height: 8px; border-radius: 99px; overflow: hidden; background: var(--line); margin: 6px 0 12px; }
.meterbar .b { background: var(--up); } .meterbar .s { background: var(--down); }
@media (max-width: 720px) { .sigs { grid-template-columns: 1fr; } }

/* ---- vatsal panel / setups / strike check ---- */
.vpanel { display: grid; grid-template-columns: 1.1fr 2fr; gap: 16px; }
.vstat { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; align-content: start; }
.vstat div, .lvl div { background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.vstat span, .lvl span { display: block; font-size: 11px; color: var(--muted); }
.vstat b { font: 600 14px var(--mono); }
.lvl { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 8px; }
.lvl b { font: 600 13px var(--mono); }
.lvl .near { border-color: var(--accent); }
.note { font-size: 12px; color: var(--muted); margin: 10px 0 0; }
.setups { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 14px; }
.setup header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.setup h3 { margin: 0; font-size: 15px; font-weight: 600; padding: 0; }
.setup .tagok { font-size: 11px; color: var(--up); border: 1px solid rgba(22,199,132,.4); border-radius: 4px; padding: 1px 6px; }
.setup .tagno { font-size: 11px; color: var(--warn); border: 1px solid rgba(240,185,11,.4); border-radius: 4px; padding: 1px 6px; }
.setup .rr { margin-left: auto; font: 700 13px var(--mono); }
.plan { display: grid; grid-template-columns: 70px 1fr auto; gap: 4px 10px; font-size: 12px; align-items: baseline; }
.plan span { color: var(--muted); } .plan b { font: 600 13px var(--mono); text-align: right; }
.plan i { font-style: normal; color: #aab4c8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.legs { width: 100%; border-collapse: collapse; font: 12px var(--mono); margin-top: 10px; }
.legs th { color: var(--muted); font-weight: 600; font-size: 11px; text-align: right; padding: 4px 6px; border: 0; border-bottom: 1px solid var(--line); }
.legs td { text-align: right; padding: 4px 6px; border: 0; border-bottom: 1px solid var(--line); color: var(--text); }
.legs th:first-child, .legs td:first-child { text-align: left; }
.sc { display: grid; grid-template-columns: 1fr 1.2fr; gap: 16px; }
.facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; align-content: start; }
.facts div { background: var(--bg-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.facts span { display: block; font-size: 11px; color: var(--muted); } .facts b { font: 600 13px var(--mono); }
.checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.checks li { display: grid; grid-template-columns: 18px 1fr; gap: 8px; font-size: 13px; margin: 0; }
.checks li small { display: block; color: var(--muted); font: 11px var(--mono); }
.checks .ok { color: var(--up); } .checks .no { color: var(--down); }
.score { font: 700 20px var(--mono); }
@media (max-width: 980px) { .vpanel, .sc { grid-template-columns: 1fr; } .facts { grid-template-columns: repeat(2, 1fr); } }
</style>
"""

GROUPS = {
    "Intraday": ["price", "vwap", "rsi_5m", "vol_ratio_5m", "day_change_pct", "day_high", "day_low", "orb_high", "orb_low"],
    "Fundamentals": ["pe", "pb", "roe", "debt_to_equity", "revenue_growth", "earnings_growth", "profit_margin", "market_cap_cr", "sector"],
    "Options": ["spot", "expiry", "days_to_expiry", "pcr_oi", "max_pain", "atm_iv", "call_wall", "put_wall"],
    "Market": ["nifty", "nifty_change_pct", "nifty_30d_pct", "nifty_pe", "vix", "vix_change_pct", "nifty_adv_dec", "fii_net_cr", "dii_net_cr"],
}
HIDDEN = {"symbol", "exchange", "price_time", "high_52w", "low_52w"}
e = html.escape


def fmt(v, d=2):
    """Indian digit grouping like toLocaleString('en-IN'): 16,89,417.04"""
    if v is None:
        return "—"
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    ip, _, fp = f"{abs(v):.{d}f}".partition(".")
    fp = fp.rstrip("0")
    if len(ip) > 3:
        head, parts = ip[:-3], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        ip = ",".join([head, *parts, ip[-3:]])
    return ("-" if v < 0 and (ip != "0" or fp) else "") + ip + (f".{fp}" if fp else "")


def signed(v):
    return "—" if v is None else f"{'+' if v > 0 else ''}{fmt(v)}%"


def direction(v):
    return "" if not v else "up" if v > 0 else "down"


def tone(label):
    label = label or ""
    if re.match(r"NO[ _]", label):
        return "t-flat"
    if re.search(r"PREMIUM|HEDGE|WATCH", label):
        return "t-warn"
    if re.search(r"BUY|BULL|APPLY|INVEST", label):
        return "t-up"
    if re.search(r"SELL|BEAR", label):
        return "t-down"
    return "t-flat"


def title(s):
    return s.replace("_", " ").title()


def topbar(m):
    m = m or {}
    ticks = [
        ("NIFTY 50", fmt(m.get("nifty")), m.get("nifty_change_pct"), ""),
        ("INDIA VIX", fmt(m.get("vix")), m.get("vix_change_pct"), ""),
        ("ADV/DEC", fmt(m.get("nifty_adv_dec")), None, ""),
        ("FII ₹CR", fmt(m.get("fii_net_cr"), 0), None, direction(m.get("fii_net_cr"))),
        ("DII ₹CR", fmt(m.get("dii_net_cr"), 0), None, direction(m.get("dii_net_cr"))),
    ]
    strip = "".join(
        f'<div class="tick"><span>{k}</span><b class="{cls}">{v}</b>'
        + (f'<i class="{direction(c)}">{signed(c)}</i>' if c is not None else "") + "</div>"
        for k, v, c, cls in ticks)
    return (f'<div class="topbar"><div class="brand"><i class="logo"></i>'
            f'<span>TRADE<b>ADVISOR</b></span><em>NSE · BSE</em></div><div class="strip">{strip}</div></div>')


def _range(label, lo, hi, v):
    if lo is None or hi is None or v is None:
        return ""
    pos = min(100, max(0, (v - lo) / (hi - lo) * 100)) if hi > lo else 50
    return (f'<div class="range"><div class="muted">{label} range</div><div class="bar"><i style="left:{pos:.1f}%"></i></div>'
            f'<div class="ends mono"><span>{fmt(lo)}</span><span>{fmt(hi)}</span></div></div>')


def quote(r):
    m = r["metrics"]
    price = m.get("price") or m.get("close")
    tags = f'<span class="tag">{e(r["exchange"])}</span>' + (f'<span class="tag">{e(m["sector"])}</span>' if m.get("sector") else "")
    kpis = "".join(f"<div><span>{k}</span><b>{fmt(v)}</b></div>" for k, v in
                   [("VWAP", m.get("vwap")), ("RSI", m.get("rsi")), ("ATR %", m.get("atr_pct")),
                    ("P/E", m.get("pe")), ("PCR", m.get("pcr_oi")), ("ATM IV", m.get("atm_iv"))])
    chg = m.get("day_change_pct")
    return (f'<section class="panel quote"><div><div class="sym">{e(r["symbol"])} {tags}</div>'
            f'<div class="px"><span class="mono big">₹{fmt(price)}</span><span class="mono chg {direction(chg)}">{signed(chg)}</span></div>'
            f'<div class="muted mono asof">as of {e(str(m.get("price_time", "—"))[:16])} IST</div></div>'
            f'<div class="ranges">{_range("Day", m.get("day_low"), m.get("day_high"), price)}'
            f'{_range("52 week", m.get("low_52w"), m.get("high_52w"), price)}</div>'
            f'<div class="kpis">{kpis}</div></section>')


def _cond(c):
    if c["op"] == "between":
        return f"in {c['value'][0]}–{c['value'][1]}"
    if isinstance(c["value"], str):
        return f"{c['op']} {c['value']} {fmt(c['target'])}"
    return f"{c['op']} {fmt(c['value'])}"


def verdicts(r):
    cards = []
    for name in r["order"]:
        v = r["verdicts"][name]
        t = tone(v["verdict"])
        groups = []
        for label, checks in v["checks"].items():
            passed = sum(c["pass"] for c in checks)
            rows = "".join(
                f'<li class="{"pass" if c["pass"] else "fail"}"><span class="dot"></span>'
                f'<span class="mono metric" title="{e(c["metric"])}">{e(c["metric"])}</span>'
                f'<span class="mono cond" title="{e(_cond(c))}">{e(_cond(c))}</span>'
                f'<span class="mono actual">{fmt(c["actual"])}</span></li>' for c in checks)
            groups.append(
                f'<div class="group {"won" if label == v["verdict"] else ""}"><div class="ghead">'
                f'<span class="lbl {tone(label)}">{e(label.replace("_", " "))}</span>'
                f'<span class="meter"><i style="width:{passed / len(checks) * 100:.0f}%"></i></span>'
                f'<span class="mono muted">{passed}/{len(checks)}</span></div><ul>{rows}</ul></div>')
        cards.append(f'<article class="panel card {t}"><header><h3>{e(title(name))}</h3>'
                     f'<span class="badge {t}">{e(v["verdict"].replace("_", " "))}</span></header>{"".join(groups)}</article>')
    return f'<div class="grid">{"".join(cards)}</div>'


def _oi(v):
    if v is None:
        return "—"
    a = abs(v)
    return f"{v / 1e5:.1f}L" if a >= 1e5 else f"{v / 1e3:.1f}K" if a >= 1e3 else fmt(v, 0)


def _leg(x, kind, signal):
    t = "t-up" if kind == "CE" else "t-down"
    active, dim = signal == kind, signal and signal != kind
    cls = f'oleg {t} {"active" if active else ""} {"dim" if dim else ""}'
    tag = f'<span class="badge {t}">SIGNAL</span>' if active else ""
    if not x:
        return (f'<div class="{cls}"><div class="olabel">Best {kind}{tag}</div>'
                f'<p class="muted" style="font-size:12px">No {kind} strike passes your liquidity filters (min OI / max spread).</p></div>')
    stats = [("Delta", fmt(x["delta"], 3)), ("IV", f"{fmt(x['iv'])}%"), ("OI", _oi(x["oi"])), ("ΔOI", _oi(x["chg_oi"])),
             ("Volume", _oi(x["volume"])), ("Bid / Ask", f"{fmt(x['bid'])} / {fmt(x['ask'])}"), ("Spread", f"{fmt(x['spread_pct'])}%"),
             ("Breakeven", f"{fmt(x['breakeven'])} ({x['breakeven_move_pct']:+.2f}%)")]
    dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in stats)
    return (f'<div class="{cls}"><div class="olabel">Best {kind}{tag}</div>'
            f'<div class="ostrike">{fmt(x["strike"])} <span>{kind}</span></div>'
            f'<div class="oprem">₹{fmt(x["ltp"])} <span class="muted">premium</span></div><dl>{dl}</dl></div>')


def option_buy(p, m):
    sig = p["signal"]
    head = (f'<div class="sec">Option buy<span class="muted">expiry {e(p["expiry"])} · {e(title(p["advisor"]))} advisor says '
            f'<b>{e(str(p["verdict"] or "not run"))}</b></span></div>')
    badge = f'<span class="badge lg {"t-up" if sig == "CE" else "t-down" if sig == "PE" else "t-flat"}">{"BUY " + sig if sig else "NO SIGNAL"}</span>'
    note = (f"{e(str(p['verdict']))} maps to the {sig} side. The best liquid strike is highlighted." if sig
            else f"{e(str(p['verdict'] or 'No verdict'))} doesn't map to CE or PE, so both sides are shown for reference only.")
    levels = "".join(f"<span>{k} <b class='{c}'>{fmt(v)}</b></span>" for k, v, c in [
        ("Spot", p["spot"], ""), ("ATM", p["atm"], ""), ("Support (put wall)", m.get("put_wall"), "up"),
        ("Resistance (call wall)", m.get("call_wall"), "down"), ("Max pain", m.get("max_pain"), ""), ("PCR", m.get("pcr_oi"), "")])
    max_oi = max([1] + [(rw[k] or {}).get("oi", 0) for rw in p["chain"] for k in ("CE", "PE")])

    def side(o, kind, strike):
        itm = strike < p["spot"] if kind == "CE" else strike > p["spot"]
        picked = p[kind] and p[kind]["strike"] == strike
        cls = f'{"itm" if itm else ""} {"pick" if picked else ""} {"active" if picked and sig == kind else ""}'
        if not o:
            return f'<td class="{cls}"></td>' * 5
        bar = (f'<td class="{cls} oi {kind.lower()}"><i class="{kind.lower()}" style="width:calc({o["oi"] / max_oi * 100:.0f}% - 12px)"></i>'
               f'<span>{_oi(o["oi"])}</span></td>')
        chg = "up" if o["chg_oi"] > 0 else "down" if o["chg_oi"] < 0 else ""
        cells = [f'<td class="{cls}">{"—" if o["delta"] is None else f"{o["delta"]:.2f}"}</td>',
                 f'<td class="{cls} ltp">{fmt(o["ltp"])}</td>', f'<td class="{cls}">{fmt(o["iv"])}</td>',
                 f'<td class="{cls} {chg}">{_oi(o["chg_oi"])}</td>']
        return bar + "".join(reversed(cells)) if kind == "CE" else "".join(cells) + bar

    body = "".join(
        f'<tr class="{"atm" if rw["strike"] == p["atm"] else ""}">{side(rw["CE"], "CE", rw["strike"])}'
        f'<td class="strike">{fmt(rw["strike"])}</td>{side(rw["PE"], "PE", rw["strike"])}</tr>' for rw in p["chain"])
    table = ('<div class="ochain"><table><thead><tr><th colspan="5" class="hc up">CALLS</th><th class="hc">Strike</th>'
             '<th colspan="5" class="hc down">PUTS</th></tr><tr><th>OI</th><th>ΔOI</th><th>IV</th><th>LTP</th><th>Δ</th><th></th>'
             '<th>Δ</th><th>LTP</th><th>IV</th><th>ΔOI</th><th class="pe-oi">OI</th></tr></thead>'
             f'<tbody>{body}</tbody></table></div>')
    foot = (f'<p class="muted foot">Picked from strikes with OI of at least your minimum and a bid/ask spread under your maximum. '
            f'Among those, the one whose delta is closest to {p["target_delta"]} wins. Delta is calculated from NSE\'s IV '
            f'(Black-Scholes). Change these filters on the Indicators tab.</p>')
    return (f'{head}<section class="panel obuy"><div class="osignal">{badge}<span class="muted">{note}</span></div>'
            f'<div class="olegs">{_leg(p["CE"], "CE", sig)}{_leg(p["PE"], "PE", sig)}</div>'
            f'<div class="levels">{levels}</div>{table}{foot}</section>')


def report(text):
    lines = []
    for line in text.split("\n"):
        if line.strip() == "---":
            lines.append("<hr>")
        else:
            parts = e(line).split("**")
            lines.append("<p>" + "".join(f"<b>{x}</b>" if i % 2 else x for i, x in enumerate(parts)) + "</p>")
    return ('<div class="sec">AI summary<span class="muted">explains the verdicts, never changes them, and can make mistakes</span></div>'
            f'<section class="panel report">{"".join(lines)}</section>')


def metrics(m):
    known = {k for g in GROUPS.values() for k in g}
    groups = {"Technicals": [k for k in m if k not in known and k not in HIDDEN], **GROUPS}
    colored = re.compile(r"change_pct|30d_pct|from_52w|growth|ret_|net_cr")
    out = []
    for g, keys in groups.items():
        rows = "".join(f'<tr><td>{e(k)}</td><td class="{direction(m[k]) if colored.search(k) and isinstance(m[k], (int, float)) else ""}">'
                       f"{e(fmt(m[k]))}</td></tr>" for k in keys if k in m)
        if rows:
            out.append(f'<section class="panel"><h4>{g}</h4><table><tbody>{rows}</tbody></table></section>')
    return f'<div class="sec">All metrics</div><div class="metrics">{"".join(out)}</div>'


def context_strip(m, iv_rank=None):
    """Timeframe biases, upcoming corporate event and IV rank, in one line above the signals."""
    tf = lambda v: badge_html("BULLISH" if v == 1 else "BEARISH" if v == -1 else "NEUTRAL") if v is not None else '<span class="muted">—</span>'
    parts = [f'<span class="muted">15m</span> {tf(m.get("mtf_15m"))}', f'<span class="muted">1h</span> {tf(m.get("mtf_1h"))}',
             f'<span class="muted">Daily</span> {tf(m.get("mtf_1d"))}']
    if m.get("mtf_aligned"):
        parts.append('<span class="badge t-up" style="font-size:10px">ALL TIMEFRAMES AGREE</span>')
    ev = m.get("days_to_event")
    parts.append(f'<span class="badge t-warn">EVENT IN {int(ev)} DAY{"S" if ev != 1 else ""}</span> <span class="muted">{e(m["event"])}</span>'
                 if ev is not None else '<span class="muted">no corporate event scheduled</span>')
    if iv_rank is not None:
        parts.append(f'<span class="muted">IV rank</span> <b class="mono">{iv_rank}</b>')
    return ('<div class="sec">Timeframes &amp; events<span class="muted">bias = majority of price vs EMA 50, MACD vs signal, '
            f'Supertrend</span></div><section class="panel"><div class="osignal">{"".join(f"<span>{p}</span>" for p in parts)}</div></section>')


def signals_panel(m):
    bull, bear, score = int(m.get("sig_bull") or 0), int(m.get("sig_bear") or 0), int(m.get("sig_score") or 0)
    label = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "MIXED"
    total = max(1, bull + bear)

    def col(side, title, cls):
        items = [(m.get(f"sig_{k}") == 1, lab) for k, sd, lab in sigmod.SIGNALS if sd == side]
        items.sort(key=lambda x: not x[0])  # active first
        return (f'<div class="{cls}"><h4 class="{"up" if side == "bull" else "down"}">{title} · {sum(a for a, _ in items)}</h4><ul>'
                + "".join(f'<li class="{"on" if a else ""}"><i></i>{e(lab)}</li>' for a, lab in items) + "</ul></div>")

    return (f'<div class="sec">Signals<span class="muted">breakouts, breakdowns, MACD, RSI, Supertrend, volume · daily candles '
            f'unless marked intraday · 20-day resistance {fmt(m.get("resistance_20d"))} / support {fmt(m.get("support_20d"))}</span></div>'
            f'<section class="panel"><div class="osignal">{badge_html(label)}<span class="mono">score {score:+d}</span>'
            f'<span class="muted">{bull} bullish · {bear} bearish active</span></div>'
            f'<div class="meterbar"><i class="b" style="width:{bull / total * 100:.0f}%"></i><i class="s" style="width:{bear / total * 100:.0f}%"></i></div>'
            f'<div class="sigs">{col("bull", "Bullish", "bull")}{col("bear", "Bearish", "bear")}</div>'
            '<p class="note">Each signal is also a rule metric (sig_resistance_break, sig_macd_above_signal, sig_rsi_oversold …, '
            'plus sig_score = bullish − bearish) for the Rules tab.</p></section>')


def _dir_label(v, up="BULLISH", down="BEARISH"):
    return up if v == 1 else down if v == -1 else "NEUTRAL"


def vatsal_panel(m):
    """Vatsal's indicator at a glance: bias, last signal, and the levels it draws, nearest first."""
    sig = lambda d, age: "—" if not d else f"{'BUY' if d > 0 else 'SELL'} · {int(age)} bars ago"
    stats = [("Daily bias", badge_html(_dir_label(m.get("vs_bias")))), ("5-min bias", badge_html(_dir_label(m.get("vs5m_bias")))),
             ("Daily signal", f"<b>{sig(m.get('vs_signal'), m.get('vs_signal_age'))}</b>"),
             ("5-min signal", f"<b>{sig(m.get('vs5m_signal'), m.get('vs5m_signal_age'))}</b>"),
             ("EMA 50/200 cross", f"<b>{'—' if m.get('vs_cross_age') is None else str(int(m['vs_cross_age'])) + ' bars ago'}</b>"),
             ("In zone", f"<b>{'Supply' if m.get('in_supply') else 'Demand' if m.get('in_demand') else 'FVG' if m.get('in_fvg') else 'None'}</b>")]
    price = m.get("price") or m.get("close") or 0
    names = [("S3", "pivot_s3"), ("S2", "pivot_s2"), ("S1", "pivot_s1"), ("Pivot", "pivot_p"), ("R1", "pivot_r1"),
             ("R2", "pivot_r2"), ("R3", "pivot_r3"), ("Fib 0", "fib_0"), ("Fib 0.5", "fib_05"), ("Fib 1", "fib_1"),
             ("Demand", "demand_top"), ("Supply", "supply_bottom"), ("Bull FVG", "fvg_bull_top"), ("Bear FVG", "fvg_bear_bottom")]
    lv = sorted([(m[k], n) for n, k in names if isinstance(m.get(k), (int, float))])
    near = {min(lv, key=lambda x: abs(x[0] - price))[1]} if lv else set()
    cells = "".join(f'<div class="{"near" if n in near else ""}"><span>{n}</span>'
                    f'<b class="{"up" if v < price else "down"}">{fmt(v)}</b></div>' for v, n in lv)
    return ('<div class="sec">Vatsal\'s indicator<span class="muted">EMA 5/13 trigger · EMA 200 filter · EMA 50/200 cross · '
            'pivots · fib · supply/demand · fair value gaps</span></div>'
            '<section class="panel"><div class="vpanel"><div class="vstat">'
            + "".join(f"<div><span>{k}</span>{v}</div>" for k, v in stats)
            + f'</div><div><div class="lvl">{cells}</div><p class="note">Green levels are below the price (support), red '
            f'above (resistance); the blue-bordered one is nearest. Daily levels.</p></div></div></section>')


def badge_html(label):
    return f'<span class="badge {tone(label)}">{e(label.replace("_", " "))}</span>'


def setups(items, bias, vatsal_mode):
    """items: [(setup, legs)]. Cards sorted with the trend-aligned ones first."""
    if not items:
        return ""
    cards = []
    for st, legs in items:
        sgn = 1 if st["side"] == "LONG" else -1
        t = "t-up" if sgn > 0 else "t-down"
        aligned = bias == sgn
        tag = (f'<span class="tagok">with the trend</span>' if aligned else
               f'<span class="tagno">counter-trend</span>' if bias else "")
        rr_c = "up" if st["rr"] >= 1.5 else "" if st["rr"] >= 1 else "down"
        act, act_why = st["verdict"]
        rows = [("Entry", st["entry"], st["entry_why"]), ("Stop", st["stop"], st["stop_why"]),
                ("Target 1", st["t1"], st["t1_why"])] + ([("Target 2", st["t2"], st["t2_why"])] if st["t2"] else [])
        plan = "".join(f"<span>{k}</span><i>{e(str(why))}</i><b>{fmt(v)}</b>" for k, v, why in rows)
        table = ""
        if legs:
            body = "".join(f"<tr><td>{l['label']} {fmt(l['strike'])} {l['kind']}</td><td>{fmt(l['ltp'])}</td><td>{fmt(l['delta'], 2)}</td>"
                           f"<td>{fmt(l['prem_stop'])}</td><td>{fmt(l['prem_t1'])}</td>"
                           f"<td>{'—' if l['rr'] is None else fmt(l['rr'])}</td></tr>" for l in legs)
            table = ('<table class="legs"><thead><tr><th>Option</th><th>Premium</th><th>Δ</th><th>@ stop</th><th>@ T1</th>'
                     f'<th>R:R</th></tr></thead><tbody>{body}</tbody></table>')
        cards.append((act == "AVOID", not aligned, -st["rr"],
                      f'<article class="panel card setup {tone(act) if act != "AVOID" else "t-flat"}"><header>'
                      f'<span class="badge lg {tone(act) if act != "AVOID" else "t-warn"}">{act}</span>'
                      f'<h3>{st["side"].title()} · {e(st["kind"])}</h3>{tag}<span class="rr {rr_c}">R:R {fmt(st["rr"])}</span></header>'
                      f'<div class="plan">{plan}</div><p class="note">{e(act_why)} · risk {fmt(st["risk_pct"])}% of price.</p>{table}</article>'))
    cards.sort(key=lambda c: c[:3])
    levels_src = "option walls, VWAP, EMAs, day high/low" + (", your pivots, fib and supply/demand zones" if vatsal_mode else "")
    return ('<div class="sec">Trade setups<span class="muted">arithmetic on your levels, not advice. Check them before acting</span></div>'
            f'<div class="setups">{"".join(c[3] for c in cards)}</div>'
            f'<p class="note">Levels used: {levels_src}. Stops sit just beyond the nearest level behind the entry; targets are the next '
            'levels ahead. Option premiums at stop/target are Black-Scholes estimates on each strike\'s own IV, anchored to its '
            'live price, assuming the move happens today (time decay would lower them).</p>')


def strike_check(r):
    if "error" in r:
        return f'<div class="alert">{e(r["error"])}</div>'
    x = r["leg"]
    passed = sum(c["pass"] for c in r["checks"])
    facts = [("Premium", f"₹{fmt(x['ltp'])}"), ("Moneyness", f"{r['moneyness']} ({r['distance_pct']:+.2f}%)"),
             ("Delta", fmt(x["delta"], 3)), ("IV / ATM IV", f"{fmt(x['iv'])}% / {fmt(r['atm_iv'])}%"),
             ("Time decay / day", f"₹{fmt(r['theta_day'])}"), ("Breakeven", fmt(x["breakeven"])),
             ("Move needed", f"{fmt(r['breakeven_need'])} pts"), ("1-σ move to expiry", f"{fmt(r['expected_move'])} pts"),
             ("P(expires ITM)", f"{fmt(r['prob_itm'])}%"), ("P(beyond breakeven)", f"{fmt(r['prob_breakeven'])}%"),
             ("OI / ΔOI", f"{_oi(x['oi'])} / {_oi(x['chg_oi'])}"), ("Build-up", r["buildup"])]
    if r["target"]:
        facts.append((f"@ {r['target'][1]} {fmt(r['target'][0])}", f"≈ ₹{fmt(r['prem_at_target'])}"))
    if r["stop"]:
        facts.append((f"@ {r['stop'][1]} {fmt(r['stop'][0])}", f"≈ ₹{fmt(r['prem_at_stop'])}"))
    checks = "".join(f'<li><span class="{"ok" if c["pass"] else "no"}">{"✓" if c["pass"] else "✗"}</span>'
                     f'<div>{e(c["name"])}<small>{e(c["detail"])}</small></div></li>' for c in r["checks"])
    vt = {"BUY": "t-up", "SELL": "t-down"}.get(r["verdict"], "t-warn")
    return (f'<section class="panel"><div class="osignal" style="margin-bottom:14px"><span class="badge lg {vt}">{r["verdict"]}</span>'
            f'<span>{e(r["verdict_why"])}</span></div><div class="sc"><div><div class="osignal" style="margin-bottom:10px">'
            f'<span class="badge {"t-up" if r["kind"] == "CE" else "t-down"}">{fmt(r["strike"])} {r["kind"]}</span>'
            f'<span class="muted">expiry {e(r["expiry"])} · spot {fmt(r["spot"])}</span></div>'
            '<div class="facts">' + "".join(f"<div><span>{e(k)}</span><b>{e(str(v))}</b></div>" for k, v in facts) + '</div></div>'
            f'<div><div class="score">{passed}/{len(r["checks"])} <span class="muted" style="font-size:13px">checks pass</span></div>'
            f'<ul class="checks" style="margin-top:10px">{checks}</ul>'
            '<p class="note">BUY: liquid, breakeven inside the 1-σ move, IV ≤ 1.2× ATM and ≥ 2/3 of direction checks agree. '
            'SELL: liquid but ≤ 1/3 agree, so writing it (or exiting if you hold it) fits the setup better. AVOID: illiquid or mixed. '
            'Probabilities are risk-neutral estimates from the option\'s IV, not forecasts. Premiums at levels '
            'assume the move happens today.</p></div></div></section>')


# ---- candlestick chart: TradingView lightweight-charts inside a component iframe ----

CHART = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
html,body{margin:0;background:transparent;color:#e6ebf5;font:14px Inter,system-ui,sans-serif}
.panel{background:rgba(15,22,38,.82);border:1px solid #1e2a42;border-radius:12px;padding:16px}
.chead{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.seg{display:flex;border:1px solid #2a3a58;border-radius:8px;overflow:hidden}
.seg button{background:#0b1220;border:0;padding:5px 12px;font:600 12px 'JetBrains Mono',monospace;color:#7d8aa5;cursor:pointer}
.seg button.on{background:#3b82f6;color:#fff}
.ohlc{display:flex;gap:14px;flex-wrap:wrap;font:12px 'JetBrains Mono',monospace;color:#7d8aa5}
.ohlc b{color:#e6ebf5;font-weight:600}.ohlc b.up{color:#16c784}.ohlc b.down{color:#ea3943}
.legend{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 4px}
.legend button{display:inline-flex;align-items:center;gap:6px;background:#0b1220;border:1px solid #1e2a42;border-radius:6px;padding:3px 9px;font:12px Inter,sans-serif;color:#c3cbdc;cursor:pointer}
.legend button i{width:14px;height:3px;border-radius:2px;background:var(--c)}
.legend button i.dash{background:repeating-linear-gradient(90deg,var(--c) 0 4px,transparent 4px 7px)}
.legend button i.dot{background:repeating-linear-gradient(90deg,var(--c) 0 2px,transparent 2px 4px)}
.legend button b{font:600 12px 'JetBrains Mono',monospace;color:#e6ebf5}
.legend button.off{opacity:.4}.legend button.off i{--c:#7d8aa5}
.hint{font-size:11px;color:#7d8aa5;align-self:center;margin-left:4px}
#chart{height:460px}
</style></head><body><section class="panel">
<div class="chead"><div class="seg" id="iv"></div><div class="ohlc" id="ohlc"></div></div>
<div class="legend" id="legend"></div><div id="chart"></div></section>
<script src="https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"></script>
<script>
const ALL = __DATA__, WALLS = __WALLS__;
const {createChart, createSeriesMarkers, CandlestickSeries, LineSeries, HistogramSeries, ColorType, CrosshairMode, LineStyle} = LightweightCharts;
const UP = '#16c784', DOWN = '#ea3943', PIVOT = '#ff9800';
// Vatsal's MA colours (MA1 5 yellow, MA2 13 red, MA3 20 cyan, MA4 50 blue); others fall back to a validated palette
const EMA_BY_PERIOD = {5: '#f5d90a', 13: '#ff6b6b', 20: '#22c3d6', 50: '#3987e5', 200: '#d55181'};
const FALLBACK = ['#c98500', '#9b6bff', '#8fa3bf'];
const emaColor = (k, n) => EMA_BY_PERIOD[+k.replace('ema_', '')] || FALLBACK[n % FALLBACK.length];
const ZONE = {supply: 'rgba(125,138,165,.20)', demand: 'rgba(0,150,136,.24)',
  fvg_bull: 'rgba(245,217,10,.16)', fvg_bear: 'rgba(255,152,0,.18)', climax_up: 'rgba(22,199,132,.16)',
  climax_down: 'rgba(234,57,67,.16)', rising_up: 'rgba(59,130,246,.16)', rising_down: 'rgba(155,89,182,.18)'};
const FIBC = {'0': '#8fa3bf', '0.5': '#16c784', '1': '#8fa3bf'};

// shaded boxes from a start time to the right edge (zones stay live until broken)
class Zones {
  constructor(zones) { this.zones = zones; }
  attached({chart, series}) { this.chart = chart; this.series = series; }
  updateAllViews() {}
  paneViews() {
    const self = this;
    return [{zOrder: () => 'bottom', renderer: () => ({draw(target) {
      if (hidden.zones) return;
      target.useBitmapCoordinateSpace(({context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr, mediaSize}) => {
        for (const z of self.zones) {
          let x1 = self.chart.timeScale().timeToCoordinate(z.t1); if (x1 == null) x1 = 0;
          const y1 = self.series.priceToCoordinate(z.top), y2 = self.series.priceToCoordinate(z.bottom);
          if (y1 == null || y2 == null) continue;
          ctx.fillStyle = ZONE[z.kind] || 'rgba(125,138,165,.15)';
          ctx.fillRect(x1 * hr, y1 * vr, (mediaSize.width - x1) * hr, Math.max(1, (y2 - y1) * vr));
        }
      });
    }})}];
  }
}
const fmt = v => v == null ? '—' : v.toLocaleString('en-IN', {maximumFractionDigits: 2});
const fmtVol = v => v >= 1e7 ? (v / 1e7).toFixed(2) + ' Cr' : v >= 1e5 ? (v / 1e5).toFixed(1) + ' L' : fmt(Math.round(v));
const hidden = {pivots: false, fib: false, zones: false, signals: false}; let chart, series = {}, wallLines = [], vsLines = {fib: [], pivots: []}, markerApi = null, cur = ALL['1D'] ? '1D' : Object.keys(ALL)[0], hover = null;
const walls = [['call_wall', 'Call wall', DOWN], ['put_wall', 'Put wall', UP], ['max_pain', 'Max pain', '#7d8aa5']].filter(([k]) => WALLS[k] != null);

function readout() {
  const d = ALL[cur], i = hover ?? d.time.length - 1, intraday = cur.endsWith('m');
  const chg = d.close[i] - (i > 0 ? d.close[i - 1] : d.open[i]), pct = i > 0 ? chg / d.close[i - 1] * 100 : 0;
  document.getElementById('ohlc').innerHTML =
    `<span>${new Date(d.time[i] * 1000).toISOString().slice(0, intraday ? 16 : 10).replace('T', ' ')}</span>` +
    ['open', 'high', 'low', 'close'].map(k => `<span>${k[0].toUpperCase()} <b>${fmt(d[k][i])}</b></span>`).join('') +
    `<b class="${chg >= 0 ? 'up' : 'down'}">${chg >= 0 ? '+' : ''}${fmt(chg)} (${pct.toFixed(2)}%)</b>` +
    (d.volume[i] > 0 ? `<span>Vol <b>${fmtVol(d.volume[i])}</b></span>` : '');
  const keys = Object.keys(d.lines);
  document.getElementById('legend').innerHTML = keys.map((k, n) => {
    const vw = k === 'vwap', c = vw ? '#e6ebf5' : emaColor(k, n);
    return `<button data-k="${k}" class="${hidden[k] ? 'off' : ''}"><i class="${vw ? 'dash' : ''}" style="--c:${c}"></i>${vw ? 'VWAP' : k.replace('ema_', 'EMA ')} <b>${fmt(d.lines[k][i])}</b></button>`;
  }).join('') + (walls.length ? `<button data-k="walls" class="${hidden.walls ? 'off' : ''}"><i class="dot" style="--c:${DOWN}"></i>Option walls <b>${walls.map(([k, t]) => t.split(' ')[0] + ' ' + fmt(WALLS[k])).join(' · ')}</b></button>` : '')
    + vsToggles(d)
    + (!cur.endsWith('m') && !keys.includes('vwap') ? '<span class="hint">VWAP shows on 5m / 15m</span>' : '');
  document.querySelectorAll('#legend button').forEach(b => b.onclick = () => { hidden[b.dataset.k] = !hidden[b.dataset.k]; applyHidden(); readout(); });
}

function vsToggles(d) {
  const v = d.vatsal || {}, b = (k, label, c, cls) => `<button data-k="${k}" class="${hidden[k] ? 'off' : ''}"><i class="${cls}" style="--c:${c}"></i>${label}</button>`;
  return (v.markers && v.markers.length ? b('signals', `Signals <b>${v.markers.length}</b>`, UP, '') : '')
    + (v.pivots ? b('pivots', `Pivots <b>P ${fmt(v.pivots.P)}</b>`, PIVOT, 'dot') : '')
    + (v.fib ? b('fib', `Fib <b>0.5 ${fmt(v.fib.levels['0.5'])}</b>`, FIBC['0.5'], 'dot') : '')
    + (v.zones && v.zones.length ? b('zones', `Zones <b>${v.zones.length}</b>`, '#009688', '') : '')
    + (v.zones && v.zones.some(z => z.kind.startsWith('fvg')) ? `<span class="hint">yellow = bullish FVG · orange = bearish FVG</span>` : '');
}

function applyHidden() {
  for (const k of ['fib', 'pivots']) for (const l of vsLines[k]) l.applyOptions({lineVisible: !hidden[k], axisLabelVisible: !hidden[k]});
  if (markerApi) markerApi.setMarkers(hidden.signals ? [] : markersFor(ALL[cur]));
  if (chart) chart.applyOptions({});  // repaint so the zone primitive honours its toggle
  for (const [k, s] of Object.entries(series)) s.applyOptions({visible: !hidden[k]});
  for (const l of wallLines) l.applyOptions({lineVisible: !hidden.walls, axisLabelVisible: !hidden.walls});
}

function markersFor(d) {
  return ((d.vatsal || {}).markers || []).map(m => m.dir > 0
    ? {time: m.time, position: 'belowBar', color: UP, shape: 'arrowUp', text: 'BUY'}
    : {time: m.time, position: 'aboveBar', color: DOWN, shape: 'arrowDown', text: 'SELL'});
}

function draw() {
  const d = ALL[cur], box = document.getElementById('chart');
  if (chart) chart.remove();
  chart = createChart(box, {
    autoSize: true,
    layout: {background: {type: ColorType.Solid, color: 'transparent'}, textColor: '#7d8aa5', fontFamily: "'JetBrains Mono', monospace", fontSize: 11, panes: {separatorColor: '#1e2a42'}},
    grid: {vertLines: {color: 'rgba(30,42,66,.5)'}, horzLines: {color: 'rgba(30,42,66,.5)'}},
    crosshair: {mode: CrosshairMode.Normal}, rightPriceScale: {borderColor: '#1e2a42'},
    timeScale: {borderColor: '#1e2a42', timeVisible: cur.endsWith('m'), secondsVisible: false},
  });
  const candle = chart.addSeries(CandlestickSeries, {priceFormat: {type: 'custom', formatter: fmt, minMove: 0.05},
    upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN});
  candle.setData(d.time.map((t, i) => ({time: t, open: d.open[i], high: d.high[i], low: d.low[i], close: d.close[i]})));
  series = {};
  Object.keys(d.lines).forEach((k, n) => {
    const vw = k === 'vwap';
    const s = chart.addSeries(LineSeries, {color: vw ? '#e6ebf5' : emaColor(k, n), lineWidth: vw ? 2 : 1.5, lineStyle: vw ? LineStyle.Dashed : LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
    s.setData(d.lines[k].map((v, i) => v == null ? {time: d.time[i]} : {time: d.time[i], value: v}));
    series[k] = s;
  });
  const v = d.vatsal || {};
  candle.attachPrimitive(new Zones(v.zones || []));
  markerApi = createSeriesMarkers(candle, []);
  vsLines = {
    fib: v.fib ? Object.entries(v.fib.levels).map(([lv, price]) => candle.createPriceLine({price, color: FIBC[lv] || '#8fa3bf',
      lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Fib ' + lv})) : [],
    pivots: v.pivots ? Object.entries(v.pivots).map(([name, price]) => candle.createPriceLine({price, color: PIVOT,
      lineWidth: 1, lineStyle: LineStyle.SparseDotted, axisLabelVisible: true, title: name})) : [],
  };
  wallLines = walls.map(([k, title, color]) => candle.createPriceLine({price: WALLS[k], color, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title}));
  if (d.volume.some(v => v > 0)) {  // volume in its own pane: never a second y-scale on the price pane
    const vol = chart.addSeries(HistogramSeries, {priceFormat: {type: 'custom', formatter: fmtVol, minMove: 1}, priceLineVisible: false, lastValueVisible: false}, 1);
    vol.setData(d.volume.map((v, i) => ({time: d.time[i], value: v, color: d.close[i] >= d.open[i] ? 'rgba(22,199,132,.45)' : 'rgba(234,57,67,.45)'})));
    chart.panes()[1].setHeight(90);
  }
  const index = new Map(d.time.map((t, i) => [t, i]));
  chart.subscribeCrosshairMove(p => { hover = p.time != null && index.has(p.time) ? index.get(p.time) : null; readout(); });
  chart.timeScale().fitContent();
  hover = null; applyHidden(); readout();
  document.getElementById('iv').innerHTML = Object.keys(ALL).map(x => `<button class="${x === cur ? 'on' : ''}">${x}</button>`).join('');
  document.querySelectorAll('#iv button').forEach(b => b.onclick = () => { cur = b.textContent; draw(); });
}
draw();
</script></body></html>"""


def chart(candles_by_interval, walls):
    keys = ("call_wall", "put_wall", "max_pain")
    return (CHART.replace("__DATA__", json.dumps(candles_by_interval))
            .replace("__WALLS__", json.dumps({k: walls.get(k) for k in keys})))


if __name__ == "__main__":
    assert fmt(1689417.04) == "16,89,417.04" and fmt(-5353.22, 0) == "-5,353" and fmt(1189.5) == "1,189.5"
    assert fmt(22.0) == "22" and fmt(None) == "—" and fmt(0) == "0" and fmt(-0.004) == "0" and fmt("x") == "x"
    assert tone("NO HEDGE NEEDED") == "t-flat" and tone("SELL_PREMIUM") == "t-warn" and tone("BUY") == "t-up"
    print("ok")
