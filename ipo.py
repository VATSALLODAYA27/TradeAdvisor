"""IPOs: open and upcoming issues from NSE, plus GMP and company financials from ipowatch.in. Pure data, no verdicts.

NSE (official): list, dates, price band, live subscription by category (QIB / NII / retail).
ipowatch.in (unofficial): grey market premium (GMP), and each IPO's page for financials, KPIs, lots, timeline,
promoter holding and objects of the issue. GMP is an informal, unregulated quote; treat it as sentiment.
Every IPO becomes a flat dict of `ipo_*` metrics so the [ipo] section in rules.toml can judge it.
"""
import difflib
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import requests

from data import nse

GMP_URL = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
SUB = {"Qualified Institutional Buyers(QIBs)": "qib", "Non Institutional Investors": "nii",
       "Retail Individual Investors(RIIs)": "retail", "Employees": "employee", "Total": "total"}
METRICS = ["ipo_gmp", "ipo_gmp_pct", "ipo_price", "ipo_issue_cr", "ipo_min_amount", "ipo_is_sme", "ipo_days_to_close",
           "ipo_sub_total", "ipo_sub_qib", "ipo_sub_nii", "ipo_sub_retail", "ipo_revenue_cr", "ipo_pat_cr",
           "ipo_revenue_growth", "ipo_pat_growth", "ipo_roe", "ipo_roce", "ipo_ebitda_margin", "ipo_pat_margin",
           "ipo_debt_equity", "ipo_pe", "ipo_promoter_post_pct"]


def num(x):
    """'₹1,94,480' / '33.67%' / 'Approx ₹178 Crores' / '₹-' -> float or None (the first number in the text)."""
    m = re.search(r"-?\d[\d,]*\.?\d*", str(x).replace("₹-", ""))
    return float(m.group().replace(",", "")) if m else None


def _key(name):
    """Comparable company name: 'Vishal Nirmiti (O) Mainboard' and 'Vishal Nirmiti Limited' -> 'vishal nirmiti'."""
    name = re.sub(r"\((?:o|u|c|a)\)|\b(mainboard|sme|ipo|limited|ltd|private|pvt|india|the)\b", " ", name.lower())
    return " ".join(re.findall(r"[a-z0-9]+", name))


def _table(html):
    """Every <table> as a frame whose first row is the header (ipowatch tables have no <th>)."""
    out = []
    for t in pd.read_html(io.StringIO(html), extract_links=None):
        if all(isinstance(c, int) for c in t.columns) and len(t) > 1:
            t = t.iloc[1:].set_axis([str(c).strip() for c in t.iloc[0]], axis=1).reset_index(drop=True)
        out.append(t)
    return out


def gmp_table():
    """GMP rows: name key, GMP ₹, link to the IPO's page."""
    html = requests.get(GMP_URL, headers=WEB, timeout=20).text
    t = pd.read_html(io.StringIO(html), extract_links="body")[0]
    rows = []
    for _, r in t.iterrows():
        (name, link), gmp = r.iloc[0], r.iloc[1][0]
        rows.append({"key": _key(name), "name": name, "gmp": num(gmp), "url": link})
    return rows


def listing():
    """Open + upcoming equity IPOs on NSE (mainboard and SME), with the total subscription so far."""
    rows = {r["symbol"]: r for r in nse("all-upcoming-issues?category=ipo") if r.get("series") in ("EQ", "SME")}
    for r in nse("ipo-current-issue"):
        if r.get("series") in ("EQ", "SME"):
            rows[r["symbol"]] = {**rows.get(r["symbol"], {}), **r}
    return list(rows.values())


def subscription(symbol):
    """{qib, nii, retail, employee, total}: times subscribed per category, from NSE's latest bid book."""
    d = nse(f"ipo-active-category?symbol={symbol}")
    out = {SUB[r["category"]]: num(r["noOfTotalMeant"]) for r in d["dataList"] if r.get("category") in SUB}
    return out | {"updated": d.get("updateTime")}


def page(url):
    """Sections of one ipowatch IPO page, picked by their header words (the page also embeds other IPOs' tables)."""
    tables = _table(requests.get(url, headers=WEB, timeout=20).text)
    has = lambda t, *words: all(any(w.lower() in str(c).lower() for c in [*t.columns, *t.iloc[:, 0]]) for w in words)
    # a sidebar widget with ANOTHER company's financials comes first; this IPO's own tables start at its issue details
    start = next((i for i, t in enumerate(tables) if has(t, "IPO Price Band")), None)
    if start is None:
        return {}
    tables = tables[start:]
    find = lambda *words: next((t for t in tables if has(t, *words)), None)
    return {"financials": find("Revenue", "PAT"), "kpi": find("KPI", "ROE"), "issue": find("IPO Price Band"),
            "lots": find("Retail Minimum"), "timeline": find("Basis of Allotment"), "holding": find("Pre IPO Shares"),
            "objects": find("Purpose")}


def _kv(t):
    return {} if t is None else {str(r.iloc[0]).strip().rstrip(":").strip(): r.iloc[1] for _, r in t.iterrows()}


def metrics(row, gmp, sub, pg):
    """Flat metrics for the rules. Anything a source didn't give is None, which makes rules using it fail."""
    hi = num(str(row.get("issuePrice") or row.get("priceBand") or "").split("to")[-1])
    kpi, issue = _kv(pg.get("kpi")), _kv(pg.get("issue"))
    m = {k: None for k in METRICS}
    m |= {"ipo_price": hi, "ipo_is_sme": int(row.get("series") == "SME"),
          "ipo_issue_cr": num(issue.get("Issue Size")),
          "ipo_days_to_close": (datetime.strptime(row["issueEndDate"], "%d-%b-%Y").date() - datetime.now().date()).days}
    if gmp and gmp["gmp"] is not None:
        m["ipo_gmp"] = gmp["gmp"]
        m["ipo_gmp_pct"] = round(gmp["gmp"] / hi * 100, 2) if hi else None
    m |= {f"ipo_sub_{k}": sub.get(k) for k in ("total", "qib", "nii", "retail")}
    if (lots := pg.get("lots")) is not None:
        retail = lots[lots.iloc[:, 0].astype(str).str.contains("Retail Minimum")]
        m["ipo_min_amount"] = num(retail.iloc[0, -1]) if len(retail) else None
    f = pg.get("financials")
    if f is not None:  # full fiscal years only: a "June 2026" row is one quarter and would fake a collapse
        f = f[f.iloc[:, 0].astype(str).str.fullmatch(r"\s*(FY)?\s*\d{2,4}\s*")]
    if f is not None and len(f) >= 2:
        f = f.set_index(f.columns[0])
        rev, pat = f.filter(like="Revenue").iloc[:, 0].map(num), f.filter(like="PAT").iloc[:, 0].map(num)
        m |= {"ipo_revenue_cr": rev.iloc[-1], "ipo_pat_cr": pat.iloc[-1]}
        if rev.iloc[-2]:
            m["ipo_revenue_growth"] = round((rev.iloc[-1] / rev.iloc[-2] - 1) * 100, 2)
        if pat.iloc[-2] and pat.iloc[-2] > 0:
            m["ipo_pat_growth"] = round((pat.iloc[-1] / pat.iloc[-2] - 1) * 100, 2)
    pick = lambda *names: next((num(v) for k, v in kpi.items() if any(n.lower() in k.lower() for n in names) and num(v) is not None), None)
    m |= {"ipo_roe": pick("ROE"), "ipo_roce": pick("ROCE"), "ipo_ebitda_margin": pick("EBITDA"), "ipo_pat_margin": pick("PAT Margin"),
          "ipo_debt_equity": pick("Debt to equity"), "ipo_pe": pick("P/E")}
    if m["ipo_pe"] is None and hi and (eps := pick("EPS")):
        m["ipo_pe"] = round(hi / eps, 2)  # pages often leave P/E blank; upper band / EPS is the same ratio
    if (h := pg.get("holding")) is not None:
        prom = h[h.iloc[:, 0].astype(str).str.contains("Promoter")]
        m["ipo_promoter_post_pct"] = num(prom.iloc[0, -1]) if len(prom) else None
    return m


def one(row, gmps):
    """Everything about one IPO; each source fails on its own (e.g. BSE-only SME issues have no NSE bid book)."""
    match = difflib.get_close_matches(_key(row["companyName"]), [g["key"] for g in gmps], n=1, cutoff=0.6)
    gmp = next((g for g in gmps if match and g["key"] == match[0]), None)
    errors, sub, pg = {}, {}, {}
    try:
        sub = subscription(row["symbol"]) if row.get("status") == "Active" else {}
    except Exception as ex:
        errors["subscription"] = f"{type(ex).__name__}: {ex}"
    try:
        pg = page(gmp["url"]) if gmp and gmp["url"] else {}
    except Exception as ex:
        errors["financials"] = f"{type(ex).__name__}: {ex}"
    if not gmp:
        errors["gmp"] = "not listed on ipowatch.in"
    return {"row": row, "gmp": gmp, "sub": sub, "page": pg, "metrics": metrics(row, gmp, sub, pg), "errors": errors}


def listed(days=90):
    """IPOs listed on NSE in the last `days`: issue price vs listing-day open/close and the latest close (Yahoo)."""
    today = datetime.now().date()
    rows = []
    for r in nse("public-past-issues"):
        if r.get("securityType") not in ("EQ", "BE", "SME") or r.get("listingDate") in (None, "-") or not num(r.get("issuePrice")):
            continue
        day = datetime.strptime(r["listingDate"], "%d-%b-%Y").date()
        if (today - day).days <= days:
            rows.append({"company": r.get("company") or r.get("companyName"), "symbol": r["symbol"],
                         "type": "SME" if r["securityType"] == "SME" else "Mainboard", "listed": day, "issue_price": num(r["issuePrice"])})
    if not rows:
        return pd.DataFrame()
    import yfinance as yf
    tickers = [f"{r['symbol']}.NS" for r in rows]
    px = yf.download(tickers, start=min(r["listed"] for r in rows), group_by="ticker", auto_adjust=False, progress=False, threads=True)
    for r in rows:
        try:
            d = (px[f"{r['symbol']}.NS"] if len(tickers) > 1 else px).dropna(subset=["Close"])
            d = d[d.index.date >= r["listed"]]
        except KeyError:
            d = pd.DataFrame()
        if d.empty:  # Yahoo doesn't carry every SME stock
            continue
        ip = r["issue_price"]
        r |= {"listing_open": float(d["Open"].iloc[0]), "listing_gain_pct": round((d["Open"].iloc[0] / ip - 1) * 100, 2),
              "day1_close_pct": round((d["Close"].iloc[0] / ip - 1) * 100, 2), "price": float(d["Close"].iloc[-1]),
              "return_pct": round((d["Close"].iloc[-1] / ip - 1) * 100, 2)}
    return pd.DataFrame(rows).sort_values("listed", ascending=False).reset_index(drop=True)


def all_ipos():
    """[one(...)] for every open/upcoming IPO, fetched in parallel. GMP failing still returns the NSE list."""
    rows = listing()
    try:
        gmps = gmp_table()
    except Exception:
        gmps = []
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(lambda r: one(r, gmps), rows))


if __name__ == "__main__":  # offline self-check of the parsers
    assert num("₹1,94,480") == 194480 and num("33.67%") == 33.67 and num("Approx ₹178 Crores") == 178 and num("₹-") is None
    assert _key("Vishal Nirmiti (O) Mainboard") == _key("Vishal Nirmiti Limited") == "vishal nirmiti"
    row = {"symbol": "X", "series": "EQ", "issuePrice": "Rs.208 to Rs.220", "issueEndDate": "05-Oct-2099"}
    fin = pd.DataFrame({"Period Ended": ["2025", "2026", "June 2026"], "Revenue": ["₹324.86", "₹344.13", "₹7.49"],
                        "PAT": ["₹23.64", "₹24.98", "₹1.83"]})
    kpi = pd.DataFrame({"KPI": ["ROE:", "Earning Per Share (EPS):", "Price/Earning P/E Ratio:"], "Values": ["33.67%", "₹12.61 (Basic)", None]})
    m = metrics(row, {"gmp": 20.0}, {"total": 2.5, "qib": 0.9}, {"financials": fin, "kpi": kpi})
    assert m["ipo_gmp_pct"] == 9.09 and m["ipo_roe"] == 33.67 and m["ipo_pe"] == round(220 / 12.61, 2)
    assert m["ipo_revenue_growth"] == 5.93 and m["ipo_pat_growth"] == 5.67 and m["ipo_sub_qib"] == 0.9 and m["ipo_roce"] is None
    print("ok")
