"""Stock report PDF on the TradeAdvisor letterhead, made by Taursa on request: build(out, ...) -> PDF bytes.

Page header: the TradeAdvisor logo (the app's chart-line mark), name and tagline. Footer: a short disclaimer and the page
number on every page, plus a full disclaimer section at the end. Content: snapshot, 12-month chart, every advisor's
verdict and the rules behind it, results (QoQ/YoY, vs estimate), shareholding, valuation, and trade setups.
"""
import io
import os
from datetime import datetime

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import data
import setups

INK, MUTED, LINE, HEAD, PANEL = (colors.HexColor(c) for c in ("#0f172a", "#5b6474", "#d9dee8", "#eef2f8", "#f7f9fc"))
GREEN, RED, BLUE, AMBER, DARK = (colors.HexColor(c) for c in ("#16c784", "#d92d3a", "#2563eb", "#c98500", "#0b1220"))
DISCLAIMER = ("TradeAdvisor gives rule-based analysis for information and education only. It is not investment advice, and "
              "TradeAdvisor is not a SEBI-registered investment adviser or research analyst. Verdicts come only from the "
              "user's own rules applied to public data (NSE, Yahoo, screener.in), which can be delayed or wrong. Investing "
              "in securities involves risk, including loss of capital; past performance does not guarantee future results. "
              "Do your own research or consult a SEBI-registered adviser before acting.")

BODY, BOLD = "Helvetica", "Helvetica-Bold"
for path, (name, bold) in ((r"C:\Windows\Fonts\segoeui.ttf", ("Seg", "Seg-B")),
                           ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", ("DejaVu", "DejaVu-B"))):
    if os.path.exists(path):  # these fonts have the ₹ sign; Helvetica does not
        pdfmetrics.registerFont(TTFont(name, path))
        pdfmetrics.registerFont(TTFont(bold, path.replace("segoeui.ttf", "segoeuib.ttf").replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")))
        BODY, BOLD = name, bold
        break
ST = {"h1": ParagraphStyle("h1", fontName=BOLD, fontSize=18, leading=22, textColor=INK),
      "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=11.5, leading=15, textColor=INK, spaceBefore=12, spaceAfter=5),
      "p": ParagraphStyle("p", fontName=BODY, fontSize=9, leading=13, textColor=INK),
      "s": ParagraphStyle("s", fontName=BODY, fontSize=7.8, leading=10.5, textColor=MUTED),
      "c": ParagraphStyle("c", fontName=BODY, fontSize=8, leading=10.5, textColor=INK),
      "k": ParagraphStyle("k", fontName=BODY, fontSize=7.2, leading=9, textColor=MUTED),
      "v": ParagraphStyle("v", fontName=BOLD, fontSize=10, leading=13, textColor=INK)}
W = 174 * mm  # text width on A4 with 18 mm margins


def f(v, d=2, pre="", suf=""):
    if pre == "₹" and BODY == "Helvetica":  # no font with the ₹ glyph on this machine: it would print as a blank box
        pre = "Rs "
    return "—" if v is None or v != v else f"{pre}{v:,.{d}f}{suf}"


def tone(label):
    label = label or ""
    return GREEN if any(w in label for w in ("BUY", "BULL", "APPLY", "INVEST")) else \
        RED if any(w in label for w in ("SELL", "BEAR", "HEDGE_NOW")) else AMBER if "WATCH" in label else MUTED


def table(rows, widths, header=True, extra=()):
    t = Table([[c if not isinstance(c, str) else Paragraph(c, ST["c"]) for c in r] for r in rows], colWidths=widths, repeatRows=int(header))
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           *([("BACKGROUND", (0, 0), (-1, 0), HEAD)] if header else []), *extra]))
    return t


def kpis(items, cols=4):
    rows = []
    for i in range(0, len(items), cols):
        rows.append([Table([[Paragraph(k, ST["k"])], [Paragraph(v, ST["v"])]], colWidths=[W / cols - 8],
                           style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]) for k, v in items[i:i + cols]])
    return table(rows, [W / cols] * cols, header=False, extra=[("BACKGROUND", (0, 0), (-1, -1), PANEL), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                                             ("LEFTPADDING", (0, 0), (-1, -1), 6)])


def chart(d, height=60 * mm):
    """1-year daily close with EMA 50 and EMA 200 (EMAs on the full history, then cut to the last year)."""
    c = d["Close"]
    lines = {k: v.tail(250) for k, v in {"Close": c, "EMA 50": data.ema(c, 50), "EMA 200": data.ema(c, 200)}.items()}
    idx = lines["Close"].index
    dr, lp = Drawing(W, height), LinePlot()
    lp.x, lp.y, lp.width, lp.height = 30, 22, W - 40, height - 40
    lp.data = [list(enumerate(v.round(2).tolist())) for v in lines.values()]
    for i, (col, w) in enumerate(((INK, 1.2), (BLUE, 0.9), (AMBER, 0.9))):
        lp.lines[i].strokeColor, lp.lines[i].strokeWidth = col, w
    months = [i for i in range(1, len(idx)) if idx[i].month != idx[i - 1].month]
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax, lp.xValueAxis.valueSteps = 0, len(idx) - 1, months
    lp.xValueAxis.labelTextFormat = lambda i: idx[int(i)].strftime("%b %y")
    lo, hi = min(v.min() for v in lines.values()), max(v.max() for v in lines.values())
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = lo * 0.97, hi * 1.03
    for ax in (lp.xValueAxis, lp.yValueAxis):
        ax.labels.fontName, ax.labels.fontSize, ax.labels.fillColor, ax.strokeColor = BODY, 6.5, MUTED, LINE
    lp.yValueAxis.gridStrokeColor, lp.yValueAxis.visibleGrid = colors.HexColor("#eef1f6"), True
    dr.add(lp)
    for i, (name, col) in enumerate(zip(lines, (INK, BLUE, AMBER))):
        dr.add(String(32 + 55 * i, height - 10, f"— {name}", fontName=BODY, fontSize=7, fillColor=col))
    return dr


def letterhead(c, doc):
    """Logo, name and tagline at the top; the short disclaimer and page number at the bottom of every page."""
    w, h = A4
    m, top, size = 18 * mm, h - 12 * mm, 10 * mm
    c.saveState()
    c.setFillColor(DARK)
    c.roundRect(m, top - size, size, size, size * 0.27, stroke=0, fill=1)
    k, pad = size * 0.8 / 32, size * 0.1  # the app logo's path: M5 22 l7-7 5 4 10-11 in a 32-unit box
    p = c.beginPath()
    for i, (px, py) in enumerate([(5, 22), (12, 15), (17, 19), (27, 8)]):
        (p.moveTo if i == 0 else p.lineTo)(m + pad + px * k, top - pad - py * k)
    c.setStrokeColor(GREEN)
    c.setLineWidth(3 * k)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.drawPath(p, stroke=1, fill=0)
    c.setFont(BOLD, 15)
    c.setFillColor(INK)
    c.drawString(m + size + 3 * mm, top - size + 2.8 * mm, "TRADE")
    c.setFillColor(GREEN)
    c.drawString(m + size + 3 * mm + c.stringWidth("TRADE", BOLD, 15), top - size + 2.8 * mm, "ADVISOR")
    c.setFont(BODY, 7.5)
    c.setFillColor(MUTED)
    c.drawRightString(w - m, top - 3.5 * mm, "Rule-based market analysis")
    c.drawRightString(w - m, top - 7.5 * mm, "NSE · BSE")
    c.setStrokeColor(GREEN)
    c.setLineWidth(1.2)
    c.line(m, top - size - 3 * mm, w - m, top - size - 3 * mm)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(m, 14 * mm, w - m, 14 * mm)
    c.setFont(BODY, 6.8)
    c.drawString(m, 10 * mm, "Created by Vatsal · for information and education only · not investment advice · "
                             "TradeAdvisor is not SEBI-registered")
    c.drawRightString(w - m, 10 * mm, f"Page {doc.page}")
    c.restoreState()


def build(out, d, name, res=None, res_metrics=None, rules_note=None):
    """out: an advisor run (symbol, exchange, metrics, verdicts); d: daily candles; res / res_metrics: results.summary()."""
    m, v, sym = out["metrics"], out["verdicts"], out["symbol"]
    rm = res_metrics or {}
    price, chg = m.get("price") or m.get("close"), m.get("day_change_pct")
    color = lambda x: "#0e9f6e" if (x or 0) >= 0 else "#d92d3a"
    story = [Paragraph(f"{sym} <font size=10 color='#5b6474'>· {name}</font>", ST["h1"]),
             Paragraph(f"{out['exchange']} · price as of {str(m.get('price_time', '—'))[:16]} IST · report generated "
                       f"{datetime.now():%d %b %Y, %H:%M} · created by Vatsal · prepared by Taursa, the TradeAdvisor assistant", ST["s"]), Spacer(1, 6),
             kpis([("Price", f"{f(price, 2, '₹')} <font color='{color(chg)}'>{f(chg, 2, '+' if (chg or 0) >= 0 else '', '%')}</font>"),
                   ("Day range", f"{f(m.get('day_low'))} – {f(m.get('day_high'))}"),
                   ("52-week range", f"{f(m.get('low_52w'))} – {f(m.get('high_52w'))}"), ("RSI (14)", f(m.get("rsi"))),
                   ("P/E · P/B", f"{f(rm.get('val_pe'))} · {f(rm.get('val_pb'))}"), ("ROE · ROCE", f"{f(rm.get('val_roe'), 1, '', '%')} · {f(rm.get('val_roce'), 1, '', '%')}"),
                   ("Dividend yield", f(rm.get("val_div_yield"), 2, "", "%")), ("Market cap", f(rm.get("val_market_cap_cr"), 0, "₹", " cr"))])]
    if d is not None and len(d) > 30:
        story += [Paragraph("Price, last 12 months", ST["h2"]), chart(d)]

    rows = [["<b>Advisor</b>", "<b>Verdict</b>", "<b>Closest label</b>", "<b>Conditions passed</b>"]]
    for n, r in v.items():
        best = max(r["checks"].items(), key=lambda kv: sum(c["pass"] for c in kv[1]) / len(kv[1]), default=(None, []))
        rows.append([n.replace("_", " ").title(), Paragraph(f"<b>{r['verdict'].replace('_', ' ')}</b>", ParagraphStyle("t", parent=ST["c"], textColor=tone(r["verdict"]))),
                     (best[0] or "—").replace("_", " "), f"{sum(c['pass'] for c in best[1])}/{len(best[1])}" if best[0] else "—"])
    story += [KeepTogether([Paragraph("Verdicts from the rules", ST["h2"]), table(rows, [40 * mm, 40 * mm, 50 * mm, 44 * mm])])]

    if res and res.get("quarters") is not None:
        pct = lambda x: f"<font color='{color(x)}'>{f(x, 1, '+' if (x or 0) >= 0 else '', '%')}</font>" if x is not None else "—"
        beat = rm.get("res_beat")
        est = "—" if beat is None else f"<font color='{color(1 if beat else -1)}'>{'BEAT' if beat else 'MISSED'} by {abs(rm['res_eps_surprise_pct']):.1f}%</font>"
        story += [KeepTogether([Paragraph(f"Results <font size=8 color='#5b6474'>· quarter ended {res['quarters'].columns[-1]} · {res['basis']}</font>", ST["h2"]),
                                kpis([("Revenue QoQ", pct(rm.get("res_sales_qoq"))), ("Revenue YoY", pct(rm.get("res_sales_yoy"))),
                                      ("Net profit QoQ", pct(rm.get("res_profit_qoq"))), ("Net profit YoY", pct(rm.get("res_profit_yoy"))),
                                      ("EPS YoY", pct(rm.get("res_eps_yoy"))), ("EPS vs estimate", est),
                                      ("Revenue · EBITDA (TTM)", f"{f(rm.get('val_sales_ttm_cr'), 0, '₹')} · {f(rm.get('val_ebitda_ttm_cr'), 0, '₹')} cr"),
                                      ("PAT · EPS (TTM)", f"{f(rm.get('val_pat_ttm_cr'), 0, '₹')} cr · {f(rm.get('val_eps_ttm'), 2, '₹')}")])])]
    if res and res.get("holding") is not None:
        sh = lambda k: f"{f(rm.get(f'sh_{k}'), 2, '', '%')} <font size=7 color='#5b6474'>({f(rm.get(f'sh_{k}_chg'), 2, '+' if (rm.get(f'sh_{k}_chg') or 0) >= 0 else '')} QoQ)</font>"
        story += [KeepTogether([Paragraph(f"Shareholding <font size=8 color='#5b6474'>· as of {res['holding'].columns[-1]}</font>", ST["h2"]),
                                kpis([("Promoters", sh("promoter")), ("FIIs", sh("fii")), ("DIIs", sh("dii")), ("Public", sh("public"))])])]

    rows = [["<b>Advisor</b>", "<b>Label</b>", "<b>Condition</b>", "<b>Actual</b>", ""]]
    for n, r in v.items():
        for label, checks in r["checks"].items():
            for c in checks:
                cond = f"{c['metric']} in {c['value'][0]}–{c['value'][1]}" if c["op"] == "between" else \
                    f"{c['metric']} {c['op']} {c['value']}" + (f" ({f(c['target'])})" if isinstance(c["value"], str) else "")
                rows.append([n.title(), label.replace("_", " "), cond, f(c["actual"]) if isinstance(c["actual"], (int, float)) else str(c["actual"] or "—"),
                             Paragraph(f"<font color='{'#0e9f6e' if c['pass'] else '#d92d3a'}'><b>{'PASS' if c['pass'] else 'FAIL'}</b></font>", ST["c"])])
    story += [Paragraph("Every rule, checked", ST["h2"]), table(rows, [24 * mm, 24 * mm, 76 * mm, 30 * mm, 20 * mm])]

    if m.get("atr"):
        bias = 1 if m.get("close", 0) > m.get("ema_200", 0) else -1
        rows = [["<b>Setup</b>", "<b>Entry</b>", "<b>Stop</b>", "<b>Target</b>", "<b>R:R</b>", "<b>Verdict</b>"]]
        for s in setups.underlying_setups(m, m["atr"]):
            lab, why = setups.setup_verdict(s, bias)
            rows.append([f"{s['side'].title()} · {s['kind']}", f(s["entry"]), f(s["stop"]), f(s["t1"]), f(s["rr"]),
                         Paragraph(f"<b>{lab}</b> <font size=6.5 color='#5b6474'>{why}</font>", ParagraphStyle("t", parent=ST["c"], textColor=tone(lab)))])
        story += [KeepTogether([Paragraph("Trade setups <font size=8 color='#5b6474'>· arithmetic on price levels, not a forecast</font>", ST["h2"]),
                                table(rows, [40 * mm, 22 * mm, 22 * mm, 22 * mm, 16 * mm, 52 * mm])])]
    if out.get("errors"):
        story += [Spacer(1, 4), Paragraph("Unavailable: " + "; ".join(f"{k} ({e})" for k, e in out["errors"].items()), ST["s"])]
    story += [Paragraph("Disclaimer", ST["h2"]), Paragraph(DISCLAIMER, ST["s"])]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=30 * mm, bottomMargin=20 * mm,
                      title=f"{sym} report", author="TradeAdvisor").build(story, onFirstPage=letterhead, onLaterPages=letterhead)
    return buf.getvalue()


if __name__ == "__main__":  # offline self-check: a minimal run builds a valid PDF with the letterhead and disclaimer
    out = {"symbol": "TEST", "exchange": "NSE", "errors": {}, "metrics": {"price": 100.0, "day_change_pct": 1.2, "rsi": 55},
           "verdicts": {"swing": {"verdict": "BUY", "checks": {"BUY": [{"metric": "rsi", "op": ">", "value": 50, "actual": 55,
                                                                         "target": 50, "pass": True}]}}}}
    pdf = build(out, None, "Test Ltd", None, {"val_pe": 20.0})
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000
    print("ok")
