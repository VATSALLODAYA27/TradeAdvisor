r"""Morning brief: market mood, sectors, events, top setups at your reward:risk, and your open trades, as a PDF.

    .venv\Scripts\python.exe brief.py                 (Git Bash: .venv/Scripts/python.exe brief.py)
    .venv\Scripts\python.exe brief.py --min-rr 2.5 --universe "NIFTY BANK" --capital 500000

Writes briefs/brief_YYYY-MM-DD.pdf. Run it before 09:15 (by hand, or with Windows Task Scheduler).
"""
import argparse
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

import data
import history
import journal
import market
import scanner

OUT_DIR = Path(__file__).with_name("briefs")


def open_trades():
    """Open journal trades with the latest price and how far they are from stop and target."""
    df = journal.load()
    df = df[df["status"].fillna("OPEN") == "OPEN"]
    if df.empty:
        return df
    stocks = sorted({s for s, i in zip(df["symbol"], df["instrument"].fillna("Stock")) if str(i).strip().lower() == "stock"})
    last = {}
    if stocks:
        px = yf.download([f"{s}.NS" for s in stocks], period="5d", interval="1d", progress=False, auto_adjust=False)["Close"]
        px = px.to_frame(f"{stocks[0]}.NS") if isinstance(px, pd.Series) else px
        last = {s: float(px[f"{s}.NS"].dropna().iloc[-1]) for s in stocks if f"{s}.NS" in px and px[f"{s}.NS"].notna().any()}
    rows = []
    for _, r in df.iterrows():
        p = last.get(r["symbol"])
        sgn = 1 if str(r["side"]).upper() == "BUY" else -1
        state = "—" if p is None else ("stop hit" if pd.notna(r["stop"]) and (p - r["stop"]) * sgn <= 0 else
                                       "target hit" if pd.notna(r["target"]) and (p - r["target"]) * sgn >= 0 else "running")
        rows.append({"symbol": r["symbol"], "instrument": r["instrument"], "side": r["side"], "qty": r["qty"], "entry": r["entry"],
                     "stop": r["stop"], "target": r["target"], "last": p,
                     "open_pnl": None if p is None else round((p - r["entry"]) * r["qty"] * sgn, 0), "state": state})
    return pd.DataFrame(rows)


def build(min_rr=2.0, universe="NIFTY 50", capital=None, risk_pct=1.0, vmode=False):
    b = {"generated": datetime.now(), "min_rr": min_rr, "universe": universe, "errors": {}}
    steps = [("market", data.market_metrics), ("sectors", lambda: market.sectors()),
             ("events", lambda: market.events(2)), ("trades", open_trades),
             ("scan", lambda: scanner.scan(market.universe(universe), min_rr, capital, risk_pct, vmode)[0])]
    for name, fn in steps:
        try:
            b[name] = fn()
        except Exception as e:
            b[name], b["errors"][name] = None, f"{type(e).__name__}: {e}"
    if b.get("market"):
        history.record("_MARKET", b["market"])
    b["mood"] = mood(b.get("market") or {}, b.get("sectors"))
    return b


def mood(m, sec):
    """One plain line summarising the market backdrop (facts, not a forecast)."""
    if not m:
        return "Market data unavailable."
    breadth = m.get("nifty_adv_dec")
    parts = [f"NIFTY {m['nifty']:,.0f} ({m['nifty_change_pct']:+.2f}% today, {m['nifty_30d_pct']:+.1f}% in 30 days)",
             f"India VIX {m['vix']:.2f} ({'calm' if m['vix'] < 14 else 'normal' if m['vix'] < 18 else 'elevated'})",
             f"breadth {breadth:.2f} {'(more advancers)' if breadth and breadth > 1 else '(more decliners)'}" if breadth else "",
             f"FII {m['fii_net_cr']:+,.0f} cr / DII {m['dii_net_cr']:+,.0f} cr" if m.get("fii_net_cr") is not None else ""]
    if sec is not None and not sec[0].empty:
        s = sec[0]
        parts.append(f"leading: {', '.join(s.head(2)['sector'])}; lagging: {', '.join(s.tail(2)['sector'])}")
    return " · ".join(p for p in parts if p)


# ---------------- PDF ----------------

def to_pdf(b, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    fonts = r"C:\Windows\Fonts"
    body, bold = "Helvetica", "Helvetica-Bold"
    if os.path.exists(os.path.join(fonts, "segoeui.ttf")):  # Segoe UI has the ₹ sign; Helvetica does not
        pdfmetrics.registerFont(TTFont("Seg", os.path.join(fonts, "segoeui.ttf")))
        pdfmetrics.registerFont(TTFont("Seg-B", os.path.join(fonts, "segoeuib.ttf")))
        body, bold = "Seg", "Seg-B"
    ink, muted, line = colors.HexColor("#0f172a"), colors.HexColor("#5b6474"), colors.HexColor("#d9dee8")
    st = {"h1": ParagraphStyle("h1", fontName=bold, fontSize=18, leading=22, textColor=ink),
          "h2": ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=15, textColor=colors.HexColor("#1d4ed8"), spaceBefore=10, spaceAfter=4),
          "p": ParagraphStyle("p", fontName=body, fontSize=9, leading=13, textColor=ink),
          "s": ParagraphStyle("s", fontName=body, fontSize=7.8, leading=10, textColor=muted),
          "c": ParagraphStyle("c", fontName=body, fontSize=7.8, leading=10, textColor=ink)}

    def tbl(df, cols, fmt=None):
        fmt = fmt or {}
        rows = [[Paragraph(f"<b>{c}</b>", st["c"]) for c in cols.values()]]
        for _, r in df.iterrows():
            rows.append([Paragraph(fmt[c](r[c]) if c in fmt else ("—" if pd.isna(r[c]) else str(r[c])), st["c"]) for c in cols])
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, line), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf7")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    num = lambda d=2: (lambda v: "—" if v is None or pd.isna(v) else f"{v:,.{d}f}")
    pct = lambda v: "—" if v is None or pd.isna(v) else f"{v:+.2f}%"
    story = [Paragraph(f"Morning brief · {b['generated']:%A %d %B %Y, %H:%M}", st["h1"]),
             Paragraph(b["mood"], st["p"]), Spacer(1, 4),
             Paragraph("Everything below is computed from public NSE / Yahoo data and your own rules. Not investment advice.", st["s"])]
    if b.get("sectors") is not None:
        s = b["sectors"][0]
        story += [Paragraph("Sectors (sorted by today's move; RS = vs NIFTY 50)", st["h2"]),
                  tbl(s, {"sector": "Sector", "1D": "1 day", "1W": "1 week", "1M": "1 month", "1Y": "1 year", "rs_1M": "RS 1M"},
                      {k: pct for k in ("1D", "1W", "1M", "1Y", "rs_1M")})]
    if b.get("scan") is not None and not b["scan"].empty:
        best = b["scan"].drop_duplicates("symbol").head(8)
        story += [Paragraph(f"Top setups in {b['universe']} with reward:risk ≥ {b['min_rr']}", st["h2"]),
                  tbl(best, {"symbol": "Symbol", "action": "Action", "setup": "Setup", "when": "When", "entry": "Entry",
                             "stop": "Stop", "target": "Target", "rr": "R:R", "confirm": "Confirms", "qty": "Qty"},
                      {"entry": num(), "stop": num(), "target": num(), "rr": num(), "qty": num(0)})]
    if b.get("trades") is not None and not b["trades"].empty:
        story += [Paragraph("Your open trades", st["h2"]),
                  tbl(b["trades"], {"symbol": "Symbol", "side": "Side", "qty": "Qty", "entry": "Entry", "stop": "Stop",
                                    "target": "Target", "last": "Last", "open_pnl": "Open P&L ₹", "state": "State"},
                      {"entry": num(), "stop": num(), "target": num(), "last": num(), "open_pnl": num(0), "qty": num(0)})]
    if b.get("events") is not None and not b["events"].empty:
        story += [Paragraph("Corporate events today and tomorrow", st["h2"]),
                  tbl(b["events"].head(25), {"when": "Date", "symbol": "Symbol", "purpose": "Purpose"})]
    if b["errors"]:
        story += [Spacer(1, 6), Paragraph("Unavailable: " + "; ".join(f"{k} ({v})" for k, v in b["errors"].items()), st["s"])]
    path.parent.mkdir(exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=28, bottomMargin=28,
                      title="Morning brief").build(story)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-rr", type=float, default=2.0)
    ap.add_argument("--universe", default="NIFTY 50", choices=list(market.UNIVERSES))
    ap.add_argument("--capital", type=float, default=None)
    ap.add_argument("--risk-pct", type=float, default=1.0)
    a = ap.parse_args()
    b = build(a.min_rr, a.universe, a.capital, a.risk_pct)
    print(to_pdf(b, OUT_DIR / f"brief_{b['generated']:%Y-%m-%d}.pdf"))


if __name__ == "__main__":
    main()
