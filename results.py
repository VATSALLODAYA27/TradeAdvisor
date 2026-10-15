"""Quarterly results and shareholding pattern. Pure data, no verdicts.

screener.in (public company pages): last ~12 quarters of results (sales/revenue, operating profit, OPM, net profit,
EPS) and quarterly shareholding (promoters, FIIs, DIIs, government, public, number of shareholders). Consolidated
figures, or standalone when consolidated has too few quarters for a year-on-year comparison.
Also the headline ratios (market cap, P/E, book value, dividend yield, ROCE, ROE, face value) and the trailing
twelve months (TTM) of revenue, EBITDA (screener's operating profit), PAT and EPS.
Yahoo: EPS estimate vs actual per quarter, and the next results date.
QoQ = latest quarter vs the one before; YoY = latest quarter vs the same quarter a year earlier.
"""
import io
import re
import time
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

import data

SCREENER = "https://www.screener.in/company/{}/{}"
WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
METRICS = ["res_sales_qoq", "res_sales_yoy", "res_profit_qoq", "res_profit_yoy", "res_eps_yoy", "res_opm", "res_opm_change_yoy",
           "res_eps_surprise_pct", "res_beat", "res_days_to_next",
           "sh_promoter", "sh_fii", "sh_dii", "sh_public", "sh_promoter_chg", "sh_fii_chg", "sh_dii_chg", "sh_public_chg",
           "sh_promoter_chg_yoy", "sh_fii_chg_yoy", "sh_dii_chg_yoy", "sh_public_chg_yoy", "sh_holders_chg_pct",
           "val_market_cap_cr", "val_pe", "val_pb", "val_book_value", "val_face_value", "val_div_yield", "val_roce", "val_roe",
           "val_sales_ttm_cr", "val_ebitda_ttm_cr", "val_pat_ttm_cr", "val_eps_ttm"]
RATIOS = {"Market Cap": "val_market_cap_cr", "Stock P/E": "val_pe", "Book Value": "val_book_value", "Face Value": "val_face_value",
          "Dividend Yield": "val_div_yield", "ROCE": "val_roce", "ROE": "val_roe", "Current Price": "price"}
_CACHE = {}  # symbol -> (fetched at, result); the Analyze run and the panel share one download


def _num(x):
    if x is None or (isinstance(x, float) and x != x):
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(x))
    return float(m.group().replace(",", "")) if m else None


def _section(soup, sid):
    """screener's table in <section id=sid> as rows=line items, columns=quarters (oldest first), numeric."""
    sec = soup.find("section", id=sid)
    if not sec or not sec.find("table"):
        return None
    t = pd.read_html(io.StringIO(str(sec.find("table"))))[0]
    t = t.set_index(t.columns[0])
    t.index = [re.sub(r"[\s\xa0]*\+$", "", str(i)).strip() for i in t.index]
    t = t.drop(index=[i for i in t.index if i in ("Raw PDF",)], errors="ignore")
    return t.apply(lambda col: col.map(_num))


def fetch(symbol, ttl=900):
    """{'quarters', 'holding', 'estimates', 'next_date', 'basis', 'url'} for one NSE symbol; each part may be None."""
    if symbol in _CACHE and time.time() - _CACHE[symbol][0] < ttl:
        return _CACHE[symbol][1]
    out = {"quarters": None, "holding": None, "estimates": None, "next_date": None, "basis": None, "url": None,
           "ratios": {}, "pl": None}
    for basis, path in (("consolidated", "consolidated/"), ("standalone", "")):
        url = SCREENER.format(symbol, path)
        soup = BeautifulSoup(requests.get(url, headers=WEB, timeout=20).text, "lxml")
        q = _section(soup, "quarters")
        if q is not None and q.shape[1] >= 5:  # five quarters = enough for year-on-year
            ratios = {li.select_one(".name").get_text(" ", strip=True): _num(li.select_one(".value").get_text(" ", strip=True))
                      for li in soup.select("#top-ratios li") if li.select_one(".name") and li.select_one(".value")}
            out |= {"quarters": q, "holding": _section(soup, "shareholding"), "basis": basis, "url": url,
                    "ratios": ratios, "pl": _section(soup, "profit-loss")}
            break
        if out["holding"] is None:
            out["holding"] = _section(soup, "shareholding")
    t = yf.Ticker(data.yf_symbol(symbol, "NSE"))
    try:
        eh = t.earnings_history
        out["estimates"] = eh if eh is not None and len(eh) else None
    except Exception:
        pass
    try:
        ed = t.earnings_dates
        now = datetime.now(timezone.utc)
        future = [d for d in ed.index if d.to_pydatetime() > now] if ed is not None else []
        out["next_date"] = min(future).date() if future else None
    except Exception:
        pass
    _CACHE[symbol] = (time.time(), out)
    return out


def _row(t, *names):
    return next((t.loc[i] for i in t.index if any(i.lower().startswith(n.lower()) for n in names)), None)


def _pct(a, b):
    return None if a is None or b is None or b == 0 or a != a or b != b else round((a / b - 1) * 100 * (1 if b > 0 else -1), 2)


def metrics(r):
    """Flat metrics for the rules. QoQ/YoY growth in %, shareholding in % and its changes in percentage points."""
    m = {k: None for k in METRICS}
    q = r.get("quarters")
    if q is not None and q.shape[1] >= 2:
        sales, profit, eps, opm = _row(q, "Sales", "Revenue"), _row(q, "Net Profit"), _row(q, "EPS"), _row(q, "OPM", "Financing Margin")
        for key, s in (("sales", sales), ("profit", profit)):
            if s is not None:
                m[f"res_{key}_qoq"] = _pct(s.iloc[-1], s.iloc[-2])
                m[f"res_{key}_yoy"] = _pct(s.iloc[-1], s.iloc[-5]) if len(s) >= 5 else None
        if eps is not None and len(eps) >= 5:
            m["res_eps_yoy"] = _pct(eps.iloc[-1], eps.iloc[-5])
        if opm is not None:
            m["res_opm"] = opm.iloc[-1]
            m["res_opm_change_yoy"] = round(opm.iloc[-1] - opm.iloc[-5], 2) if len(opm) >= 5 else None
    e = r.get("estimates")
    if e is not None:
        last = e.dropna(subset=["epsActual", "epsEstimate"]).tail(1)
        if len(last) and last["epsEstimate"].iloc[0]:
            surprise = (last["epsActual"].iloc[0] / last["epsEstimate"].iloc[0] - 1) * 100 * (1 if last["epsEstimate"].iloc[0] > 0 else -1)
            m |= {"res_eps_surprise_pct": round(surprise, 2), "res_beat": int(surprise > 0)}
    if r.get("next_date"):
        m["res_days_to_next"] = (r["next_date"] - datetime.now().date()).days
    rt = r.get("ratios") or {}
    m |= {key: rt.get(name) for name, key in RATIOS.items() if key in m}
    if rt.get("Book Value") and rt.get("Current Price"):
        m["val_pb"] = round(rt["Current Price"] / rt["Book Value"], 2)
    pl = r.get("pl")
    if pl is not None and pl.shape[1]:  # last column is TTM (trailing twelve months) when screener has it
        last = lambda *names: (lambda s: None if s is None or s.iloc[-1] != s.iloc[-1] else s.iloc[-1])(_row(pl, *names))
        m |= {"val_sales_ttm_cr": last("Sales", "Revenue"), "val_ebitda_ttm_cr": last("Operating Profit"),
              "val_pat_ttm_cr": last("Net Profit"), "val_eps_ttm": last("EPS")}
    h = r.get("holding")
    if h is not None and h.shape[1] >= 1:
        rows = {"promoter": _row(h, "Promoters"), "fii": _row(h, "FIIs"), "dii": _row(h, "DIIs"), "public": _row(h, "Public")}
        for k, s in rows.items():
            if s is None and k == "promoter":  # screener drops the row for companies with no promoter (HDFC Bank)
                s = pd.Series([0.0] * h.shape[1], index=h.columns)
            if s is not None:
                m[f"sh_{k}"] = s.iloc[-1]
                m[f"sh_{k}_chg"] = round(s.iloc[-1] - s.iloc[-2], 2) if len(s) >= 2 else None
                m[f"sh_{k}_chg_yoy"] = round(s.iloc[-1] - s.iloc[-5], 2) if len(s) >= 5 else None
        holders = _row(h, "No. of Shareholders")
        if holders is not None and len(holders) >= 2:
            m["sh_holders_chg_pct"] = _pct(holders.iloc[-1], holders.iloc[-2])
    return m


def summary(symbol):
    """(raw tables, metrics) for one symbol, or (None, {}) for indices and unknown symbols."""
    if symbol in data.INDEX_YF or symbol in getattr(data, "COMMODITY_YF", {}):
        return None, {}
    r = fetch(symbol)
    return r, metrics(r)


if __name__ == "__main__":  # offline self-check on screener-shaped tables
    cols = ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"]
    q = pd.DataFrame([[100, 110, 120, 125, 130], [10, 11, 12, 10, 15], [1.0, 1.1, 1.2, 1.0, 1.5], [20, 21, 22, 20, 23]],
                     index=["Sales", "Net Profit", "EPS in Rs", "OPM %"], columns=cols, dtype=float)
    h = pd.DataFrame([[50, 50, 50, 49, 48], [20, 21, 22, 22, 23], [15, 15, 16, 17, 17], [15, 14, 12, 12, 12], [1000, 1100, 1200, 1300, 1430]],
                     index=["Promoters", "FIIs", "DIIs", "Public", "No. of Shareholders"], columns=cols, dtype=float)
    est = pd.DataFrame({"epsActual": [1.0, 1.5], "epsEstimate": [1.1, 1.2]})
    m = metrics({"quarters": q, "holding": h, "estimates": est, "next_date": None})
    assert m["res_sales_qoq"] == 4.0 and m["res_sales_yoy"] == 30.0 and m["res_profit_yoy"] == 50.0 and m["res_eps_yoy"] == 50.0
    assert m["res_opm"] == 23 and m["res_opm_change_yoy"] == 3 and m["res_eps_surprise_pct"] == 25.0 and m["res_beat"] == 1
    assert m["sh_promoter"] == 48 and m["sh_promoter_chg"] == -1 and m["sh_promoter_chg_yoy"] == -2 and m["sh_fii_chg"] == 1
    assert m["sh_holders_chg_pct"] == 10.0 and m["sh_public_chg_yoy"] == -3
    assert _pct(-5, -10) == 50.0  # a loss halving is +50%, not -50%
    pl = pd.DataFrame([[900, 1000], [180, 200], [80, 88], [5.0, 5.5]], index=["Sales", "Operating Profit", "Net Profit", "EPS in Rs"],
                      columns=["Mar 2026", "TTM"], dtype=float)
    v = metrics({"ratios": {"Market Cap": 16000, "Stock P/E": 22.1, "Book Value": 668, "Current Price": 1223, "Face Value": 10,
                            "Dividend Yield": 0.5, "ROCE": 10.3, "ROE": 8.91}, "pl": pl})
    assert (v["val_pe"], v["val_pb"], v["val_face_value"], v["val_div_yield"]) == (22.1, 1.83, 10, 0.5)
    assert (v["val_ebitda_ttm_cr"], v["val_pat_ttm_cr"], v["val_eps_ttm"], v["val_market_cap_cr"]) == (200, 88, 5.5, 16000)
    assert metrics({"pl": pl.drop(index="Operating Profit")})["val_ebitda_ttm_cr"] is None  # banks: no EBITDA line
    no_prom = metrics({"holding": h.drop(index="Promoters")})
    assert no_prom["sh_promoter"] == 0.0 and no_prom["sh_promoter_chg"] == 0.0
    print("ok")
