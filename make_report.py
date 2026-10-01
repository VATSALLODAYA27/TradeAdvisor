r"""Builds PersonalTradeAdvisor_Report.pdf. Code snippets are extracted from the real project files with `ast`.

    .venv\Scripts\python.exe make_report.py   (needs: pip install reportlab)
"""
import ast
import os
from datetime import date
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "PersonalTradeAdvisor_Report.pdf")
F = r"C:\Windows\Fonts"
pdfmetrics.registerFont(TTFont("Body", os.path.join(F, "segoeui.ttf")))
pdfmetrics.registerFont(TTFont("Body-Bold", os.path.join(F, "segoeuib.ttf")))
pdfmetrics.registerFont(TTFont("Body-Italic", os.path.join(F, "segoeuii.ttf")))
pdfmetrics.registerFont(TTFont("Mono", os.path.join(F, "consola.ttf")))
pdfmetrics.registerFont(TTFont("Mono-Bold", os.path.join(F, "consolab.ttf")))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")

INK, MUTED, ACCENT, GREEN, RED, CODEBG, LINE = (colors.HexColor(x) for x in
                                                ("#0f172a", "#5b6474", "#1d4ed8", "#0e9f6e", "#d03a45", "#f3f5f9", "#d9dee8"))

S = {
    "title": ParagraphStyle("title", fontName="Body-Bold", fontSize=26, leading=32, textColor=INK, spaceAfter=6),
    "sub": ParagraphStyle("sub", fontName="Body", fontSize=12, leading=17, textColor=MUTED),
    "h1": ParagraphStyle("h1", fontName="Body-Bold", fontSize=17, leading=22, textColor=INK, spaceBefore=6, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=12.5, leading=17, textColor=ACCENT, spaceBefore=10, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName="Body-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=6, spaceAfter=2),
    "p": ParagraphStyle("p", fontName="Body", fontSize=9.6, leading=14, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Body", fontSize=8.4, leading=11.5, textColor=MUTED, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=8.4, leading=11, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=8.4, leading=11, textColor=INK),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=7.4, leading=9.4, textColor=INK, backColor=CODEBG,
                           borderColor=LINE, borderWidth=0.5, borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=8),
    "center": ParagraphStyle("center", fontName="Body", fontSize=9, leading=12, textColor=MUTED, alignment=TA_CENTER),
}


def P(text, style="p"):
    return Paragraph(text, S[style])


def bullets(items, style="p"):
    return ListFlowable([ListItem(P(t, style), leftIndent=12, value="•") for t in items], bulletType="bullet",
                        start="•", leftIndent=12, bulletFontName="Body", bulletFontSize=9)


def code(text):
    text = text.replace("✓", "v").replace("✗", "x")  # the two glyphs Consolas lacks
    return Preformatted(text.rstrip(), S["code"], maxLineLength=118, newLineChars="  ")


def source(file, name, max_lines=None, start=None):
    """Exact source of a top-level (or class-level) definition in a project file."""
    path = os.path.join(ROOT, file)
    text = open(path, encoding="utf-8").read()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            lines = ast.get_source_segment(text, node).splitlines()
            if start:
                lines = lines[start:]
            if max_lines and len(lines) > max_lines:
                lines = lines[:max_lines] + ["    ...  # (continues in " + file + ")"]
            return "\n".join(lines)
    raise KeyError(f"{name} not in {file}")


def lines_of(file, first, last):
    return "\n".join(open(os.path.join(ROOT, file), encoding="utf-8").read().splitlines()[first - 1:last])


def find_lines(file, startswith, count):
    rows = open(os.path.join(ROOT, file), encoding="utf-8").read().splitlines()
    i = next(n for n, r in enumerate(rows) if r.startswith(startswith))
    return "\n".join(rows[i:i + count])


def table(rows, widths, header=True, zebra=True):
    data = [[P(escape(str(c)) if not str(c).startswith("<") else str(c), "cellb" if header and r == 0 else "cell")
             for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf7")))
    if zebra:
        style += [("BACKGROUND", (0, r), (-1, r), colors.HexColor("#fafbfd")) for r in range(2, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


def step(n, title, what, why, files, extra=None):
    body = [P(f'<font color="#1d4ed8">Step {n}</font> · {title}', "h2"),
            P("<b>What we did.</b> " + what), P("<b>Why.</b> " + why), P(f"<b>Files:</b> <font name='Mono'>{files}</font>", "small")]
    if extra:
        body += extra
    return body


def notes(items):
    return [P("<b>Syntax, line by line</b>", "h3"), bullets(items, "p")]


# ---------------- architecture diagram ----------------

def box(d, x, y, w, h, text, fill="#eef3ff", stroke="#1d4ed8", size=8):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=colors.HexColor(fill), strokeColor=colors.HexColor(stroke), strokeWidth=0.8))
    for i, line in enumerate(text.split("\n")):
        d.add(String(x + w / 2, y + h / 2 + 3 - i * (size + 2) + (len(text.split(chr(10))) - 1) * (size + 2) / 2,
                     line, fontName="Body-Bold" if i == 0 else "Body", fontSize=size if i == 0 else size - 1,
                     textAnchor="middle", fillColor=INK))


def arrow(d, x1, y1, x2, y2):
    d.add(Line(x1, y1, x2, y2, strokeColor=MUTED, strokeWidth=0.9))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    d.add(Polygon([x2, y2, x2 - 6 * math.cos(a - 0.4), y2 - 6 * math.sin(a - 0.4), x2 - 6 * math.cos(a + 0.4),
                   y2 - 6 * math.sin(a + 0.4)], fillColor=MUTED, strokeColor=MUTED))


def diagram():
    d = Drawing(515, 300)
    box(d, 190, 262, 135, 32, "You (browser)\nlocalhost:8501", "#f1f5f9", "#5b6474")
    box(d, 160, 205, 195, 36, "app.py  (Streamlit)\ntabs.py · views.py (look)", "#ecfdf5", "#0e9f6e")
    arrow(d, 257, 262, 257, 242)
    box(d, 10, 130, 150, 50, "advisor.py (LangGraph)\ncollect → advisors (parallel)\n→ option_pick → report")
    box(d, 182, 130, 150, 50, "setups.py · scanner.py\ntrade setups, strike check,\nopportunities")
    box(d, 354, 130, 150, 50, "journal.py · market.py\ntrades.csv dashboard,\nNSE scanners")
    for x in (85, 257, 429):
        arrow(d, 257, 205, x, 181)
    box(d, 10, 60, 150, 44, "data.py\nmetrics + indicators\n+ candles for the chart")
    box(d, 182, 60, 150, 44, "vatsal.py · signals.py\nyour TradingView setup,\n26 named signals")
    box(d, 354, 60, 150, 44, "option_pick.py\nbest CE / PE (Black-Scholes)\ncalled by advisor.py")
    arrow(d, 85, 130, 85, 105)
    arrow(d, 257, 130, 257, 105)
    arrow(d, 160, 82, 182, 82)
    box(d, 10, 4, 150, 34, "NSE public API\noption chain, VIX, FII/DII, scanners", "#fff7ed", "#c2410c")
    box(d, 182, 4, 150, 34, "yfinance (Yahoo)\nhistory, 5-min bars, fundamentals", "#fff7ed", "#c2410c")
    box(d, 354, 4, 150, 34, "Groq (free LLM)\nsummary, called by advisor.py", "#fff7ed", "#c2410c")
    arrow(d, 85, 38, 85, 60)
    arrow(d, 257, 38, 110, 60)
    box(d, 380, 214, 125, 30, "rules.toml · indicators.json\nyour rules & settings", "#fefce8", "#a16207", 7.5)
    arrow(d, 380, 229, 356, 223)
    return d


# ---------------- page furniture ----------------

def on_page(c, doc):
    c.saveState()
    c.setFont("Body", 7.5)
    c.setFillColor(MUTED)
    c.drawString(40, 22, "PersonalTradeAdvisor · project report")
    c.drawRightString(A4[0] - 40, 22, f"page {doc.page}")
    c.setStrokeColor(LINE)
    c.line(40, 32, A4[0] - 40, 32)
    c.restoreState()


def build():
    story = []
    W = A4[0] - 80

    # ---------- cover ----------
    story += [Spacer(1, 70), P("PersonalTradeAdvisor", "title"),
              P("A rules-based, multi-agent trade <b>verdict</b> system for NSE &amp; BSE. What we built, step by step, "
                "why each choice was made, and how the code works.", "sub"), Spacer(1, 18)]
    story.append(table([
        ["Item", "Detail"],
        ["Date", date.today().strftime("%d %B %Y")],
        ["Language / UI", "Python 3.13 · Streamlit (web UI) · LangGraph (multi-agent graph)"],
        ["Data (free)", "NSE public JSON API · yfinance (Yahoo Finance)"],
        ["AI summary", "Groq free tier (openai/gpt-oss-120b) - explains verdicts, never decides them"],
        ["Size", "≈ 3,200 lines across 18 files · 5 offline test files"],
        ["Run it", "cd PersonalTradeAdvisor  →  .\\.venv\\Scripts\\streamlit.exe run app.py  →  http://localhost:8501"],
    ], [90, W - 90]))
    story += [Spacer(1, 16), P("<b>Important.</b> The app never places orders. Every BUY / SELL / AVOID comes from rules and "
                               "arithmetic you can read and change; it is a tool for your own analysis, not investment advice. "
                               "Markets can move against any signal.", "small"), PageBreak()]

    # ---------- contents ----------
    story += [P("Contents", "h1"), bullets([
        "1. The project in one page", "2. The journey: 17 steps from an empty folder", "3. Architecture and file map",
        "4. Code walkthrough with syntax notes (every module)", "5. The formulas behind the numbers",
        "6. Bugs we found and how we fixed them", "7. How it is tested", "8. Limits you should know",
        "9. What more we can implement", "10. Glossary"]), PageBreak()]

    # ---------- 1 overview ----------
    story += [P("1. The project in one page", "h1"),
              P("You asked for a multi-agent trade advisor built with LangGraph covering <b>stocks (intraday)</b>, "
                "<b>options</b>, <b>long-term buy/sell</b>, <b>swing</b> and <b>hedge</b> trades, using real-time data. "
                "Along the way you set three ground rules that shaped everything:"),
              bullets(["<b>Verdicts only.</b> \"I don't want to buy or sell anything, I just want to pass a verdict.\" "
                       "So the system never talks to a broker's order API.",
                       "<b>Your metrics decide.</b> \"I will set some metrics; based on that you pass the verdict.\" So every "
                       "verdict comes from a rules file you control, not from an AI's opinion.",
                       "<b>Free data.</b> Zerodha and Groww charge ≈ ₹500/month for live market data through their APIs, so we "
                       "use NSE's public website API plus Yahoo Finance."]),
              P("What the app does today", "h2"),
              table([
                  ["Tab", "What you get"],
                  ["Analyze", "Type RELIANCE or NIFTY 22700 PE. Price header, TradingView-style chart (EMAs, VWAP, option walls, "
                              "your Vatsal overlays), 26 named signals, verdict cards per advisor, option-buy pick, trade setups "
                              "with BUY/SELL/AVOID, strike check, AI summary, all metrics."],
                  ["Opportunities", "Scan NIFTY 50 / Bank / IT / Auto / Pharma / Next 50 / all F&O for setups meeting YOUR minimum "
                                    "reward:risk; buy price, stop-loss, target, when to act, quantity for your capital; option legs."],
                  ["Market", "Live NSE scanners: volume shockers, most bought (top value, price up), most active, gainers, "
                             "losers, OI spurts, most active option contracts."],
                  ["Journal", "Log trades (or add them from a scan), close them with an exit price; P&L, win rate, avg R, "
                              "profit factor, drawdown, equity curve, P&L by symbol. Saved in trades.csv."],
                  ["Rules", "Visual editor for rules.toml: per advisor, ordered verdicts, each a list of conditions; live ✓/✗."],
                  ["Indicators", "Your periods (EMA, SMA, RSI, MACD, ATR, Bollinger, Supertrend, volume, opening range) and "
                                 "option-pick filters."],
              ], [70, W - 70]), PageBreak()]

    # ---------- 2 journey ----------
    story.append(P("2. The journey: 17 steps from an empty folder", "h1"))
    story.append(P("Each step lists what we did, why we did it that way, and the files it touched. Later steps sometimes "
                   "replaced earlier ones; that is noted where it happened."))
    story += step(1, "Plan before code",
                  "Started from an empty folder. Designed the flow: <i>collect data once → compute signals with normal code → "
                  "let each advisor apply rules → optionally let an LLM explain</i>.",
                  "An LLM is bad at arithmetic (it would miscompute RSI or Greeks) and non-deterministic. Plain code is exact "
                  "and testable; the LLM is only good at writing a readable explanation.", "(design only)")
    story += step(2, "Pick free, real data sources",
                  "Researched Zerodha Kite Connect (free 'Personal' plan has no market data; data costs ₹500/month) and "
                  "Groww Trade API (₹499/month for live data). Probed NSE endpoints: <font name='Mono'>quote-equity</font> "
                  "was blocked (403) but <font name='Mono'>option-chain-v3</font>, <font name='Mono'>allIndices</font> and "
                  "<font name='Mono'>fiidiiTradeReact</font> worked. Yahoo covers NSE (.NS) and BSE (.BO) history.",
                  "You asked for free sources. The trade-off: Yahoo's 5-minute bars lag ≈ 5 minutes and NSE's public API is "
                  "unofficial (it can change). Both limits are documented in the code with <font name='Mono'>ponytail:</font> "
                  "comments.", "data.py")
    story += step(3, "Build the data collector",
                  "<font name='Mono'>collect(symbol)</font> merges five independent sources (daily, intraday, fundamentals, "
                  "options, market) into one flat dict of metrics. If one fails (e.g. a BSE-only stock has no options) the "
                  "others still work.",
                  "Rules need one simple namespace of numbers (rsi, vwap, pcr_oi …). Independence means one broken source "
                  "never blanks the whole screen.", "data.py")
    story += step(4, "Rules engine and LangGraph agents",
                  "You clarified: verdict only, your metrics. So we created <font name='Mono'>rules.toml</font>: each "
                  "<font name='Mono'>[section]</font> is an advisor; each label (BUY, SELL, …) is a list of "
                  "<font name='Mono'>[metric, op, value]</font> conditions; the first label whose conditions all pass wins. "
                  "LangGraph runs all advisors in parallel after one collect step.",
                  "TOML is human-editable and part of Python's standard library (tomllib). First-match-wins is easy to reason "
                  "about. Parallel nodes keep each advisor independent.", "rules.toml, advisor.py, test_rules.py")
    story += step(5, "AI summary: Anthropic → Groq (free)",
                  "Initially wired to the Claude API. You asked why a key was needed and whether it was free; it is paid "
                  "(≈ ₹3-4 per analysis), so we switched to <b>Groq's free tier</b> with a plain HTTP call. Groq had retired "
                  "Llama 3.3, so we queried your key's model list and chose <font name='Mono'>openai/gpt-oss-120b</font>.",
                  "The summary is optional and never changes a verdict, so a free model is enough. We also taught the prompt "
                  "that <font name='Mono'>_cr</font> means ₹ crore after it wrote \"5.35 bn\".", "advisor.py")
    story += step(6, "First UI: React + FastAPI",
                  "Built a dark 'trading terminal' UI in React (Vite) with a FastAPI backend: controls, verdict cards with "
                  "pass/fail per rule, metrics tables, a rules editor that validates before saving.",
                  "You asked for a proper UI with a financial look. (Replaced in step 10, but its design lives on.)",
                  "web/ and api.py (both later deleted)")
    story += step(7, "Candlestick chart",
                  "Added TradingView's open-source <font name='Mono'>lightweight-charts</font>: candles, EMA lines, volume in "
                  "its own pane, 5m/15m/1D/1W switch, hover readout (O/H/L/C, change, volume, EMA values).",
                  "It is the same engine TradingView uses, fast and free. EMA colours were validated for colour-blind contrast; "
                  "volume gets its own pane so there is never a confusing second y-axis on the price chart.", "views.py (chart)")
    story += step(8, "VWAP, option walls, rule builder, indicator settings",
                  "Session VWAP on intraday charts; call wall / put wall / max pain as labelled lines; a visual rule builder; "
                  "<font name='Mono'>indicators.json</font> for your periods (EMA/SMA lists, RSI, MACD, ATR, Bollinger, "
                  "Supertrend, volume average, opening range).",
                  "You wanted to set your own metrics and indicator settings. Metric names follow settings "
                  "(EMA 21 → <font name='Mono'>ema_21</font>) so rules stay readable.", "data.py, indicators.json")
    story += step(9, "Option buy: best CE / PE strike",
                  "The options advisor's verdict chooses the side (BULLISH → CE, BEARISH → PE). Among liquid strikes "
                  "(minimum OI, maximum bid/ask spread) the one whose delta is closest to your target (0.5 ≈ ATM) wins. NSE "
                  "does not publish delta, so we compute it from NSE's implied volatility with Black-Scholes.",
                  "You asked for the best spot to buy on the CE or PE side. Delta is the standard way to pick 'how far OTM'; "
                  "liquidity filters stop the app recommending strikes you cannot actually trade.", "option_pick.py")
    story += step(10, "Switch to Streamlit; delete React and FastAPI",
                  "You asked to use Streamlit, then to delete React/FastAPI. We removed <font name='Mono'>web/</font> and "
                  "<font name='Mono'>api.py</font>, uninstalled FastAPI (kept uvicorn: Streamlit needs it), and fixed two "
                  "launch issues (port 8000 in use; use <font name='Mono'>.\\.venv\\Scripts\\streamlit.exe</font> in PowerShell).",
                  "One language (Python), one command to run, no npm build. The trade-off is less design freedom, which "
                  "step 11 recovered.", "app.py")
    story += step(11, "Rebuild the React look inside Streamlit",
                  "Moved the look into <font name='Mono'>views.py</font>: one CSS block plus HTML builders rendered with "
                  "<font name='Mono'>st.html</font>, and the chart embedded with <font name='Mono'>components.html</font>. "
                  "Widgets are styled through the <font name='Mono'>st-key-…</font> classes Streamlit adds to keyed widgets.",
                  "You preferred the React design. Pure string builders are easy to test and keep app.py about flow, not styling.",
                  "views.py, app.py")
    story += step(12, "Vatsal's indicator (opt-in) + Fair Value Gap",
                  "Ported your TradingView 'All Indicator Combo – Tradefinder' settings: EMA 5/13/50/200 in your colours; "
                  "EMA 200 filter + EMA 50/200 cross; signal expiry 3 candles; alternate signals; auto-Fibonacci (0/0.5/1); "
                  "floor pivots P, S1-S3, R1-R3; supply/demand zones; PVSRA liquidity zones; Fair Value Gaps (you confirmed ON). "
                  "It is behind a toggle, so the app stays standard for everyone else.",
                  "You said: \"it should be normal for everyone; if one selects Vatsal indicator then show my metrics\". "
                  "Your leading indicator (section 03) was not shared, so the trigger is assumed to be the EMA 5/13 cross.",
                  "vatsal.py")
    story += step(13, "Trade setups, strike check, BUY / SELL / AVOID",
                  "Momentum / pullback / breakout plans in both directions from your levels, each with entry, stop, targets, "
                  "reward:risk and option legs; a strike checker (moneyness, IV vs ATM, theta/day, expected move, probability, "
                  "OI build-up, checklist); a clear label on everything; typing <font name='Mono'>nifty 22700 put</font> works.",
                  "You asked for proper trade set-ups (not only the best trade), a verdict on any strike you give, and "
                  "BUY / SELL / AVOID. The labels come from fixed, printed thresholds.", "setups.py")
    story += step(14, "Signals library",
                  "26 named signals (13 bullish, 13 bearish): resistance/support breaks, 52-week breakouts, MACD vs signal and "
                  "crosses, RSI oversold/overbought and reversals, golden/death cross, Supertrend and flips, volume "
                  "breakout/breakdown, Bollinger touches, VWAP, opening-range breaks. Each is a 0/1 rule metric plus a score.",
                  "You asked for breakouts, breakdowns, MACD above signal, RSI oversold/overbought. Named 0/1 metrics plug "
                  "straight into the rules engine (the new <font name='Mono'>[breakout]</font> advisor uses them).", "signals.py")
    story += step(15, "Market scanners and Opportunities",
                  "NSE live-analysis endpoints for volume shockers, most active, gainers/losers, OI spurts, active options. "
                  "The Opportunities scanner downloads a whole universe in one batch, builds every setup, keeps those meeting "
                  "your minimum reward:risk, ranks by confirmations, sizes the position for your capital and risk %.",
                  "You asked for volume shockers, most bought, and a section that tells which share/option to trade with buy "
                  "price, target and stop-loss using your risk:reward. (A true 'most bought on Groww' list is Groww's private "
                  "data; we use top traded value among stocks that are up.)", "market.py, scanner.py, tabs.py")
    story += step(16, "Trade journal dashboard",
                  "trades.csv with add / edit / close; P&L, win rate, average R-multiple, profit factor, max drawdown, equity "
                  "curve, P&L by symbol and by setup type.",
                  "You asked for a dashboard of your trades. CSV opens in Excel and needs no database.", "journal.py, tabs.py")
    story += step(17, "Six more: timeframes, strategies, events, history, sectors, morning brief",
                  "Multi-timeframe bias (15m / 1h / daily) with mtf_* rule metrics; a Strategies tab with 8 presets, payoff at "
                  "expiry and today, max profit/loss, breakevens, probability of profit and real NSE lot sizes; an events "
                  "calendar with a strike-check warning when results fall before expiry; a SQLite history (history.db) giving "
                  "trend charts and IV rank; a sector heatmap with strength relative to NIFTY; and brief.py, a PDF morning brief "
                  "with its own tab.",
                  "You picked these from the 'what more' list. Each reuses the same data layer and stays rule-based: strategy "
                  "'fits' are tags, not picks, and every probability is labelled as a model estimate.",
                  "data.py, market.py, strategies.py, history.py, brief.py, tabs.py, views.py")
    story.append(PageBreak())

    # ---------- 3 architecture ----------
    story += [P("3. Architecture and file map", "h1"),
              P("Arrows show who calls whom. Only the bottom row talks to the internet; everything above it is plain Python "
                "you can test offline."), diagram(), Spacer(1, 8),
              P("What one click on <b>Get verdict</b> does", "h2"),
              bullets(["<font name='Mono'>app.py</font> parses your input (<font name='Mono'>nifty 22700 put</font> → NIFTY, "
                       "22700, PE) and calls <font name='Mono'>advisor.build(names).invoke(...)</font>.",
                       "LangGraph runs <b>collect</b> (data.py fetches Yahoo + NSE in one pass), then every selected advisor "
                       "<b>in parallel</b>, then <b>option_pick</b> (needs all verdicts), then <b>report</b> (Groq).",
                       "The result is stored in <font name='Mono'>st.session_state</font>, so switching tabs or chart "
                       "timeframes never re-downloads. Candles are cached for 2 minutes.",
                       "<font name='Mono'>views.py</font> turns the result into HTML; <font name='Mono'>setups.py</font> "
                       "builds the trade plans and the strike check from the same metrics."]),
              P("File map", "h2"),
              table([
                  ["File", "Lines", "Role"],
                  ["app.py", "≈450", "Streamlit page flow: controls, Analyze tab, Rules & Indicators editors"],
                  ["tabs.py", "200", "Opportunities, Market and Journal tabs"],
                  ["views.py", "≈730", "All CSS + HTML builders + the TradingView chart (HTML/JS in a string)"],
                  ["advisor.py", "≈220", "Rules parser/validator, rule checks, LangGraph graph, Groq summary"],
                  ["data.py", "≈390", "NSE/Yahoo fetch, indicator engine, settings, candles for the chart"],
                  ["vatsal.py", "≈250", "Your TradingView setup: signals, zigzag/fib, pivots, zones, liquidity, FVG"],
                  ["signals.py", "≈100", "26 named 0/1 signals and the score"],
                  ["option_pick.py", "≈70", "Black-Scholes delta, liquidity filter, best CE/PE"],
                  ["setups.py", "≈250", "Levels, trade setups, option legs, strike check, BUY/SELL/AVOID, query parser"],
                  ["scanner.py", "≈130", "Universe scan, confirmations, position sizing, market hours"],
                  ["market.py", "≈70", "NSE market scanners and scan universes"],
                  ["journal.py", "≈80", "trades.csv load/save and dashboard statistics"],
                  ["strategies.py", "≈150", "Option strategy presets, payoff, breakevens, probability of profit"],
                  ["history.py", "≈70", "history.db (SQLite): daily snapshots, trends, IV rank"],
                  ["brief.py", "≈170", "Morning brief builder and PDF (briefs/brief_YYYY-MM-DD.pdf)"],
                  ["rules.toml", "≈60", "YOUR rules (placeholders until you replace them)"],
                  ["indicators.json", "-", "YOUR settings (created on first save; defaults live in data.py)"],
                  ["test_*.py", "≈200", "Offline self-checks; run each with python test_x.py"],
              ], [80, 40, W - 120])]

    # ---------- 4 code walkthrough ----------
    story += [P("4. Code walkthrough with syntax notes", "h1"),
              P("Every snippet below is copied automatically from the current project files, so it matches your code exactly. "
                "Long functions are cut with a <font name='Mono'># (continues …)</font> marker.")]

    story += [P("4.1 rules.toml: your rules", "h2"),
              P("TOML is a config format: <font name='Mono'>[name]</font> starts a table, <font name='Mono'>key = value</font> "
                "sets a value, <font name='Mono'>[ ... ]</font> is a list. Each rule is a 3-item list."),
              code(find_lines("rules.toml", "[swing]", 4)),
              *notes(["<font name='Mono'>[swing]</font> - one advisor. <font name='Mono'>default</font> - the verdict when no "
                      "label passes.",
                      "<font name='Mono'>[\"close\", \"&gt;\", \"ema_50\"]</font> - metric, operator, value. A string value is "
                      "another metric's name; a number is a threshold; <font name='Mono'>[45, 65]</font> goes with "
                      "<font name='Mono'>between</font>.",
                      "Labels are checked top to bottom; the first whose <b>all</b> rules pass is the verdict."])]

    story += [P("4.2 advisor.py: checking rules", "h2"), code(source("advisor.py", "check")),
              code(source("advisor.py", "verdict")),
              *notes(["<font name='Mono'>metric, op, val = rule</font> - <b>tuple unpacking</b>: a 3-item list split into 3 names.",
                      "<font name='Mono'>m.get(metric)</font> - dictionary lookup that returns <font name='Mono'>None</font> "
                      "instead of crashing when the key is missing; missing data makes a rule fail, never crash.",
                      "<font name='Mono'>OPS[op](x, target)</font> - <font name='Mono'>OPS</font> maps \"&lt;\" to "
                      "<font name='Mono'>operator.lt</font> etc., so the operator is looked up, then called like a function.",
                      "<font name='Mono'>x if cond else y</font> - Python's inline conditional.",
                      "<font name='Mono'>all(c[\"pass\"] for c in ...)</font> - a <b>generator expression</b> inside "
                      "<font name='Mono'>all()</font>: True only if every condition passed."])]

    story += [P("4.3 advisor.py: the LangGraph multi-agent graph", "h2"), code(source("advisor.py", "State")),
              code(source("advisor.py", "agent")), code(source("advisor.py", "build")),
              *notes(["<font name='Mono'>class State(TypedDict)</font> - declares the shared state's keys and types; LangGraph "
                      "passes this dict between nodes.",
                      "<font name='Mono'>Annotated[dict, operator.or_]</font> - a <b>reducer</b>. Advisors run in parallel and each "
                      "returns <font name='Mono'>{\"verdicts\": {name: …}}</font>; <font name='Mono'>operator.or_</font> is dict "
                      "merge (<font name='Mono'>a | b</font>), so all results are combined instead of overwriting each other.",
                      "<font name='Mono'>lambda s: …</font> - a small anonymous function. <font name='Mono'>agent(name)</font> "
                      "returns a new function that remembers <font name='Mono'>name</font> (a <b>closure</b>): one factory, many nodes.",
                      "<font name='Mono'>g.add_edge(\"collect\", n)</font> for every advisor = fan-out; "
                      "<font name='Mono'>add_edge(n, \"option_pick\")</font> = fan-in: LangGraph waits for all advisors.",
                      "<font name='Mono'>g.compile()</font> turns the description into a runnable graph; "
                      "<font name='Mono'>.invoke(state)</font> runs it."])]

    story += [P("4.4 advisor.py: the free AI summary (Groq)", "h2"), code(source("advisor.py", "report_node", 26)),
              *notes(["<font name='Mono'>os.environ.get(\"GROQ_API_KEY\")</font> - reads your key from the Windows environment; "
                      "the key is never written in code.",
                      "<font name='Mono'>requests.post(url, headers=…, json=…, timeout=60)</font> - an HTTP call; "
                      "<font name='Mono'>json=</font> converts the dict to JSON for you.",
                      "<font name='Mono'>if not r.ok: return …</font> - a failed summary (rate limit, bad key) only shows a note; "
                      "the verdicts still display."])]

    story += [P("4.5 data.py: fetching NSE safely", "h2"), code(source("data.py", "nse")),
              *notes(["<font name='Mono'>for attempt in range(tries)</font> + <font name='Mono'>try/except</font> - retry up to 3 "
                      "times when NSE drops the connection (your first 'no data' error).",
                      "<font name='Mono'>raise</font> with no argument re-raises the last error after the final attempt.",
                      "<font name='Mono'>time.sleep(1.5 * (attempt + 1))</font> - wait longer each time (1.5 s, 3 s): 'back-off'."])]

    story += [P("4.6 data.py: indicators with pandas", "h2"), code(source("data.py", "rsi")), code(source("data.py", "ema")),
              code(source("data.py", "indicators", 22)),
              *notes(["A pandas <b>Series</b> is a column of numbers with dates as the index. Operations like "
                      "<font name='Mono'>c.diff()</font> or <font name='Mono'>up / dn</font> apply to every row at once "
                      "(vectorised: fast, no loops).",
                      "<font name='Mono'>.ewm(span=n, adjust=False).mean()</font> - exponential moving average; "
                      "<font name='Mono'>alpha=1/n</font> is Wilder's smoothing used by RSI/ATR on TradingView.",
                      "<font name='Mono'>.clip(lower=0)</font> keeps only gains; <font name='Mono'>.rolling(n).mean()</font> is a simple "
                      "moving average.",
                      "<font name='Mono'>{**{f\"ema_{n}\": … for n in …}, \"rsi\": …}</font> - a <b>dict comprehension</b> "
                      "unpacked with <font name='Mono'>**</font> into a bigger dict; the f-string builds names like "
                      "<font name='Mono'>ema_50</font> from your settings.",
                      "One function returns every indicator as a full series: the rules use the last row, the chart draws the "
                      "whole series, so they can never disagree."])]

    story += [P("4.7 data.py: one collect for everything", "h2"), code(source("data.py", "collect")),
              *notes(["<font name='Mono'>for name, fn in [(\"daily\", lambda: …), …]</font> - a list of (label, function) pairs; "
                      "each source is tried on its own.",
                      "<font name='Mono'>out.update(fn())</font> merges each source's metrics into one dict; "
                      "<font name='Mono'>errors[name] = …</font> records which source failed and why.",
                      "<font name='Mono'>out |= …</font> - in-place dict merge (Python 3.9+).",
                      "<font name='Mono'>None if v != v</font> - NaN is the only value not equal to itself: a compact NaN check "
                      "(NaN also breaks JSON).",
                      "<font name='Mono'>numbers.Real</font> also matches numpy numbers (fixed a crash when Supertrend returned numpy ints)."])]

    story += [P("4.8 option_pick.py: Black-Scholes delta and the best strike", "h2"),
              code(source("option_pick.py", "bs_delta")), code(source("option_pick.py", "best")),
              *notes(["<font name='Mono'>math.erf</font> gives the normal distribution without SciPy: "
                      "N(x) = ½·(1 + erf(x/√2)).",
                      "Put delta = call delta − 1 (put-call parity), hence <font name='Mono'>n - 1</font>.",
                      "<font name='Mono'>min(ok, key=lambda x: abs(abs(x[\"delta\"]) - target))</font> - pick the item with the "
                      "smallest distance to your target delta; <font name='Mono'>key=</font> says what to compare.",
                      "Liquidity first (OI and spread filters), then delta: an illiquid 'perfect' strike is never chosen."])]

    story += [P("4.9 setups.py: reading 'NIFTY 22700 PUT'", "h2"),
              code(find_lines("setups.py", "# the CE/PE side is only read", 2)), code(source("setups.py", "parse_query")),
              *notes(["A <b>regular expression</b>: <font name='Mono'>([A-Z0-9][A-Z0-9&amp;_-]*?)</font> captures the symbol "
                      "(<font name='Mono'>*?</font> = as short as possible); <font name='Mono'>(\\d+(?:\\.\\d+)?)</font> the strike; "
                      "<font name='Mono'>(CE|PE|CALL|PUT|C|P)?</font> the optional side.",
                      "The side group lives <i>inside</i> the strike group, so it is only read after a number. This fixed the bug "
                      "where RELIANCE was read as RELIAN + CE.",
                      "<font name='Mono'>m.groups()</font> returns the captured parts; <font name='Mono'>{…}.get(kind, kind)</font> "
                      "maps CALL→CE, PUT→PE and leaves CE/PE unchanged."])]

    story += [P("4.10 setups.py: trade plans and BUY / SELL / AVOID", "h2"),
              code(source("setups.py", "underlying_setups", 30)), code(source("setups.py", "setup_verdict")),
              code(source("setups.py", "strike_verdict")),
              *notes(["A function defined inside another (<font name='Mono'>make</font>) can use the outer variables: here it builds "
                      "one plan for a given entry and returns a dict.",
                      "<font name='Mono'>sgn = 1 if LONG else -1</font> lets one formula serve both directions: "
                      "reward:risk = (target − entry)·sgn / (entry − stop)·sgn.",
                      "Targets further than 3×ATR are ignored (they produced a fake 27:1 plan); with no level, the plan falls back "
                      "to 1×ATR stop and 1.5×/2.5×ATR targets, labelled as such.",
                      "Thresholds for BUY / SELL / AVOID are plain <font name='Mono'>if</font> statements you can edit."])]

    story += [P("4.11 vatsal.py: your TradingView setup", "h2"), code(source("vatsal.py", "signals", 34)),
              code(source("vatsal.py", "fair_value_gaps")),
              *notes(["<font name='Mono'>np.where(cond, a, b)</font> - vectorised if/else over a whole column.",
                      "<font name='Mono'>zip(trig, bias)</font> walks two columns together; the loop keeps state (armed trigger, its "
                      "age, the last signal) that vectorised code cannot, which is how 'signal expiry' and 'alternate signal' work.",
                      "<font name='Mono'>.to_numpy()</font> converts pandas to plain numpy arrays for fast indexing like "
                      "<font name='Mono'>h[i - 2]</font>.",
                      "A Fair Value Gap is a 3-candle imbalance; it is kept until a later candle trades fully back through it."])]

    story += [P("4.12 signals.py: named signals", "h2"), code(source("signals.py", "_crossed")),
              code(source("signals.py", "daily", 24)),
              *notes(["<font name='Mono'>(a &gt; b) &amp; (a.shift() &lt;= b.shift())</font> - 'crossed above': above now, not above "
                      "one bar ago. <font name='Mono'>&amp;</font> is element-wise AND on pandas columns.",
                      "<font name='Mono'>.tail(bars).any()</font> - did it happen in the last few bars?",
                      "<font name='Mono'>int(bool(x))</font> turns every signal into 0/1 so rules can say "
                      "<font name='Mono'>[\"sig_resistance_break\", \"==\", 1]</font>."])]

    story += [P("4.13 scanner.py: sizing a position to your risk", "h2"), code(source("scanner.py", "size")),
              code(source("scanner.py", "confirmations")),
              *notes(["Quantity = (capital × risk %) ÷ (entry − stop), capped so the position fits in your capital: "
                      "<font name='Mono'>math.floor</font> rounds down to whole shares.",
                      "<font name='Mono'>sum(checks.values())</font> counts True as 1: the number of confirmations (0-4)."])]

    story += [P("4.14 journal.py: P&amp;L and R-multiple", "h2"), code(source("journal.py", "with_pnl")),
              *notes(["<font name='Mono'>.map({\"BUY\": 1, \"SELL\": -1})</font> converts text to a sign so one formula handles "
                      "long and short trades.",
                      "R-multiple = P&amp;L ÷ planned risk: 2R means you made twice what you risked.",
                      "<font name='Mono'>.where(risk &gt; 0)</font> blanks rows with no stop instead of dividing by zero."])]

    story += [P("4.15 app.py and views.py: Streamlit patterns", "h2"),
              code(source("app.py", "get_candles")), code(source("app.py", "quick_pick")), code(source("views.py", "fmt")),
              *notes(["<font name='Mono'>@st.cache_data(ttl=120)</font> - a <b>decorator</b>: results are remembered for 2 minutes "
                      "per set of arguments, so chart switches are instant.",
                      "<font name='Mono'>ThreadPoolExecutor(4)</font> + <font name='Mono'>pool.map</font> downloads the four chart "
                      "timeframes at the same time.",
                      "Streamlit reruns the whole script on every click. <font name='Mono'>st.session_state</font> is a dict that "
                      "survives reruns (the analysis result, your symbol). <font name='Mono'>on_change=quick_pick</font> is a "
                      "<b>callback</b> that runs before the rerun.",
                      "<font name='Mono'>fmt</font> formats numbers the Indian way (16,89,417.04) - lakh/crore grouping.",
                      "The chart is HTML + JavaScript in a Python string, filled with data by "
                      "<font name='Mono'>.replace(\"__DATA__\", json.dumps(...))</font> and shown with "
                      "<font name='Mono'>components.html</font>."]), PageBreak()]

    # ---------- 5 formulas ----------
    story += [P("5. The formulas behind the numbers", "h1"),
              table([
                  ["Name", "Formula (plain words)", "Where"],
                  ["EMA(n)", "Each value = previous EMA + (price − previous EMA) × 2/(n+1)", "data.ema"],
                  ["RSI(n)", "100 − 100/(1 + avg gain/avg loss), averages with Wilder smoothing (1/n)", "data.rsi"],
                  ["MACD", "EMA(12) − EMA(26); signal = EMA(9) of MACD; histogram = MACD − signal", "data.indicators"],
                  ["ATR(n)", "Wilder average of true range = max(H−L, |H−prev C|, |L−prev C|)", "data.indicators"],
                  ["Bollinger", "SMA(20) ± 2 × standard deviation; %b = (close − lower)/(upper − lower)", "data.indicators"],
                  ["Supertrend", "(H+L)/2 ± 3×ATR(10) bands that only tighten; flips when close crosses the band", "data.supertrend"],
                  ["VWAP", "Σ(typical price × volume) ÷ Σ volume, reset each day; typical = (H+L+C)/3", "data.intraday_metrics"],
                  ["Pivots", "P=(H+L+C)/3, R1=2P−L, S1=2P−H, R2=P+(H−L), S2=P−(H−L), R3=H+2(P−L), S3=L−2(H−P)", "vatsal.pivots"],
                  ["Auto Fib", "Zigzag swings (depth 10, deviation 3×ATR%); level 0 at latest swing, 1 at previous", "vatsal.fib"],
                  ["Supply/Demand", "Swing high/low (10 bars each side); zone height = ATR(50) × 2.5/10", "vatsal.supply_demand"],
                  ["FVG", "Bullish: low[i] > high[i−2]; bearish: high[i] < low[i−2]; kept until filled", "vatsal.fair_value_gaps"],
                  ["PCR", "Total put OI ÷ total call OI (nearest expiry)", "data.option_metrics"],
                  ["Max pain", "Strike where option buyers' total payout would be smallest", "data.option_metrics"],
                  ["Delta", "Call N(d1), put N(d1) − 1, d1 = [ln(S/K) + (r + σ²/2)t] / (σ√t)", "option_pick.bs_delta"],
                  ["Expected move", "Spot × ATM IV × √(days/365): one standard deviation to expiry", "setups.check_strike"],
                  ["Reward:risk", "(target − entry) ÷ (entry − stop), signs flipped for shorts", "setups.underlying_setups"],
                  ["Position size", "floor(capital × risk% ÷ |entry − stop|), capped by capital ÷ entry", "scanner.size"],
                  ["R-multiple", "trade P&L ÷ (|entry − stop| × qty)", "journal.with_pnl"],
              ], [72, W - 72 - 100, 100]), PageBreak()]

    # ---------- 6 bugs ----------
    story += [P("6. Bugs we found and how we fixed them", "h1"),
              P("Every one of these was caught by running the real thing or a test before you hit it. They are the best "
                "summary of why tests and live checks matter."),
              table([
                  ["Symptom", "Cause", "Fix"],
                  ["Wrong option walls / max pain", "NSE sent some strikes as text (\"1280\")", "Convert with float()"],
                  ["Nonsense IV on expiry day", "Used today's expiring chain", "Pick the first expiry after today"],
                  ["Crash printing the AI summary", "Windows console is cp1252, summary had ₹", "sys.stdout.reconfigure(encoding='utf-8')"],
                  ["HTTP 500 after adding Supertrend", "numpy int64 cannot be turned into JSON", "Normalise all numbers in collect()"],
                  ["No swings found on flat tops", "Pivot finder rejected ties", "TradingView rule: strict left, ties allowed right"],
                  ["ATM option leg disappeared", "OTM and ATM picked the same strike", "Choose ATM first, OTM/ITM on their own side"],
                  ["27:1 'target' 37% away", "52-week low used as first target", "Targets must be within 3×ATR"],
                  ["No SHORT setups in standard view", "No level below price to use", "ATR fallback stop/targets, labelled"],
                  ["'nifty 22700 put' → no data", "Whole text sent as a symbol; NSE dropped the connection",
                   "parse_query() + NSE retry with back-off"],
                  ["RELIANCE read as RELIAN + CE", "Side regex matched the name's last letters", "Side only after a strike number"],
                  ["First trade could not be closed", "Empty date column became datetime64", "Store plain date objects"],
                  ["New CSS not applied", "Streamlit caches imported modules", "Restart the server after editing modules"],
                  ["Port already in use", "Two servers on 8000/8501", "Stop the old one or pick another port"],
              ], [140, 170, W - 310]), PageBreak()]

    # ---------- 7 testing ----------
    story += [P("7. How it is tested", "h1"),
              P("Five offline test files check the logic with made-up data (no internet needed). Each prints "
                "<font name='Mono'>ok</font> or stops at the first wrong result."),
              code(".venv\\Scripts\\python.exe test_rules.py        # rules engine + validation\n"
                   ".venv\\Scripts\\python.exe test_indicators.py   # supertrend, RSI, settings, rules round-trip\n"
                   ".venv\\Scripts\\python.exe test_option_pick.py  # delta, liquidity filter, side mapping\n"
                   ".venv\\Scripts\\python.exe test_setups.py       # vatsal, pivots, fib, FVG, setups, strike check, parser\n"
                   ".venv\\Scripts\\python.exe journal.py           # journal P&L / R / drawdown self-check\n"
                   ".venv\\Scripts\\python.exe views.py             # number formatting self-check"),
              P("Example: the put-call parity check proves the Black-Scholes code is consistent:"),
              code(find_lines("test_setups.py", "# --- Black-Scholes", 4)),
              P("Besides the tests, every feature was run live in the browser on RELIANCE, NIFTY and TCS before being handed over."),
              P("8. Limits you should know", "h1"),
              bullets(["<b>Delayed intraday data.</b> Yahoo 5-minute bars lag ≈ 5 minutes. Tick-level data needs a paid broker feed.",
                       "<b>Unofficial NSE API.</b> It can change or block requests without notice; the app retries and shows a clear "
                       "message when it fails.",
                       "<b>Placeholder rules.</b> rules.toml still contains example rules; replace them with yours. Example: the "
                       "options rules use VWAP, which indices do not have, so NIFTY options show NO SIGNAL.",
                       "<b>Assumed trigger.</b> Vatsal's indicator uses an EMA 5/13 cross until you share Tradefinder section 03.",
                       "<b>Estimates.</b> Option premiums at stop/target, probabilities and expected move come from Black-Scholes "
                       "with a fixed 6.5% rate; they assume the move happens today and ignore volatility changes.",
                       "<b>No backtest yet.</b> Rules have not been measured on history, so nobody knows their real win rate yet "
                       "(see section 9, idea 1).",
                       "<b>Holidays.</b> Market-hours status ignores exchange holidays."]), PageBreak()]

    # ---------- 9 future ----------
    story += [P("9. What more we can implement", "h1"),
              P("Ordered by how much each would improve your decisions. Effort: S = hours, M = a day or two, L = several days."),
              table([
                  ["#", "Idea", "Why it matters", "Effort"],
                  ["1", "Backtester for your rules", "Replay each advisor over years of data: win rate, average R, drawdown. The "
                                                     "single most important next step before trusting any rule.", "M"],
                  ["2", "Alerts (Telegram / email)", "A scheduled scan that messages you when a BUY/SELL fires or price reaches a "
                                                     "planned entry, so you do not have to watch the screen.", "S-M"],
                  ["3", "Live journal tracking", "Mark open trades to market; auto-flag when stop or target is hit; unrealised P&L.", "S"],
                  ["4", "Read-only broker sync", "Kite Connect's free Personal API can read holdings and positions (no orders): feed "
                                                 "the hedge advisor your real portfolio and import fills into the journal.", "M"],
                  ["5", "Tradefinder section 03", "Port your real leading indicator (and the truncated dropdown settings) so signals "
                                                  "match TradingView exactly.", "S"],
                  ["6", "Multi-timeframe confirmation", "Require 15m, 1h and daily to agree before BUY/SELL; fewer false signals.", "S-M"],
                  ["7", "Option strategies", "Bull call / bear put spreads, straddles, iron condors with payoff charts and full "
                                             "Greeks (gamma, vega, theta); IV rank from stored daily ATM IV.", "M-L"],
                  ["8", "Lot sizes and margin", "Use NSE's lot-size file so option quantities are whole lots with margin estimates.", "S"],
                  ["9", "Events calendar", "Earnings dates, dividends, splits from NSE; warn or AVOID before results.", "S-M"],
                  ["10", "History database", "Save PCR, OI, IV and signals daily (SQLite) for trends and for the backtester.", "M"],
                  ["11", "Sector / relative strength heatmap", "See which sectors lead or lag NIFTY; scan only the strongest.", "M"],
                  ["12", "Morning brief", "A daily PDF/email before 09:15: market mood, top opportunities, open trades.", "S-M"],
                  ["13", "Paid real-time feed (optional)", "Kite Connect data (₹500/month) via websocket for tick-level intraday.", "M"],
                  ["14", "Deploy online", "Streamlit Community Cloud or a small VPS with a login, usable from your phone.", "S-M"],
                  ["15", "Portfolio risk dashboard", "Total exposure, sector concentration, correlation, worst-case loss.", "M"],
                  ["16", "Machine learning (later)", "Only after the backtester exists; otherwise it just memorises noise.", "L"],
              ], [18, 120, W - 18 - 120 - 38, 38]),
              Spacer(1, 10),
              P("Recommended order: <b>5 → 1 → 3 → 2 → 8</b>. First make your indicator exact, then measure it, then let the app "
                "watch the market for you."), PageBreak()]

    # ---------- 10 glossary ----------
    story += [P("10. Glossary", "h1"), table([
        ["Term", "Meaning"],
        ["LangGraph", "A library to build multi-step AI/agent workflows as a graph of nodes that share a state dict."],
        ["Streamlit", "A Python library that turns a script into a web app; it reruns the script on each interaction."],
        ["Advisor", "One [section] of rules.toml: a named set of verdicts and their conditions."],
        ["Metric", "One number the rules can use (rsi, vwap, pcr_oi, sig_score …)."],
        ["ATM / ITM / OTM", "At / in / out of the money: strike at, favourable to, or beyond the current price."],
        ["Delta", "How much the option price moves per ₹1 move in the underlying (0 to 1 for calls)."],
        ["IV", "Implied volatility: the market's expected yearly move, backed out of option prices."],
        ["OI / ΔOI", "Open interest (open contracts) / its change today."],
        ["PCR", "Put-call ratio of open interest; > 1 often read as bullish support, < 0.7 bearish."],
        ["Option walls", "Strikes with the highest call OI (resistance) and put OI (support)."],
        ["Reward:risk (R:R)", "Distance to target ÷ distance to stop. 2 means the target is twice the risk."],
        ["R-multiple", "A trade's result in units of the risk you planned (e.g. +2R, −1R)."],
        ["FVG", "Fair Value Gap: a 3-candle price imbalance that often acts as support/resistance."],
        ["PVSRA", "Price-volume analysis colouring 'vector' candles with unusually high volume."],
        ["TOML", "A simple config file format; Python reads it with the built-in tomllib."],
    ], [95, W - 95])]

    doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=42, bottomMargin=44,
                            title="PersonalTradeAdvisor - project report", author="PersonalTradeAdvisor")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(OUT)


if __name__ == "__main__":
    build()
