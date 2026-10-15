"""IPOs: open and upcoming issues from NSE, GMP from investorgain.com, company details from chittorgarh.com.
Pure data, no verdicts.

NSE (official): list, dates, price band, live subscription by category (QIB / NII / retail).
investorgain.com (unofficial): grey market premium (GMP), an informal, unregulated quote; treat it as sentiment.
chittorgarh.com: each IPO's page for financials, KPIs, valuation, lots, promoter holding, objects of the issue and
broker reviews (subscribe / avoid counts). Pages are found by company name from chittorgarh's current-IPO lists.
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

GMP_URL = "https://www.investorgain.com/report/live-ipo-gmp/331/"
LISTS = ["https://www.chittorgarh.com/report/ipo-in-india-list-main-board-sme/82/mainboard/",
         "https://www.chittorgarh.com/report/ipo-in-india-list-main-board-sme/82/sme/"]
WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
SUB = {"Qualified Institutional Buyers(QIBs)": "qib", "Non Institutional Investors": "nii",
       "Retail Individual Investors(RIIs)": "retail", "Employees": "employee", "Total": "total"}
METRICS = ["ipo_gmp", "ipo_gmp_pct", "ipo_price", "ipo_issue_cr", "ipo_min_amount", "ipo_is_sme", "ipo_days_to_close",
           "ipo_sub_total", "ipo_sub_qib", "ipo_sub_nii", "ipo_sub_retail", "ipo_revenue_cr", "ipo_pat_cr",
           "ipo_revenue_growth", "ipo_pat_growth", "ipo_roe", "ipo_roce", "ipo_ebitda_margin", "ipo_pat_margin",
           "ipo_debt_equity", "ipo_pe", "ipo_promoter_post_pct", "ipo_broker_subscribe", "ipo_broker_neutral",
           "ipo_broker_avoid"]


def num(x):
    """'₹1,94,480' / '33.67%' / 'Approx ₹178 Crores' / '₹-' -> float or None (the first number in the text)."""
    m = re.search(r"-?\d[\d,]*\.?\d*", str(x).replace("₹-", ""))
    return float(m.group().replace(",", "")) if m else None


def _key(name):
    """Comparable company name: 'Tonbo Imaging India IPOO', 'tonbo-imaging-india-ipo', 'Tonbo Imaging (India) Limited'
    -> 'tonbo imaging'."""
    name = re.sub(r"(IPO|SME)[OUC]$", "", name.strip())  # investorgain's Open/Upcoming/Closed flag stuck to the name
    name = re.sub(r"\((?:o|u|c|a)\)|\b(mainboard|sme|nse|bse|ipo|limited|ltd|private|pvt|india|the)\b", " ", name.lower())
    return " ".join(re.findall(r"[a-z0-9]+", name))


def _match(name, keys):
    k = _key(name)
    hit = difflib.get_close_matches(k, keys, n=1, cutoff=0.6)
    if hit:
        return hit[0]
    # 'zetwerk manufacturing businesses' (NSE's legal name) vs 'zetwerk' (the IPO's short name)
    short = [c for c in keys if c and (k.startswith(c + " ") or c.startswith(k + " "))]
    return short[0] if len(short) == 1 else None


def gmp_table():
    """GMP rows from investorgain: name key, GMP ₹ (None when it shows '₹--')."""
    t = pd.read_html(io.StringIO(requests.get(GMP_URL, headers=WEB, timeout=20).text), extract_links="body")[0]
    rows = []
    for _, r in t.iterrows():
        if not (isinstance(r.iloc[0], tuple) and isinstance(r.iloc[1], tuple)):  # blank / ad rows
            continue
        name, gmp = r.iloc[0][0], str(r.iloc[1][0])
        if isinstance(name, str) and name.strip():
            rows.append({"key": _key(name), "name": name, "gmp": None if "₹--" in gmp else num(gmp)})
    return rows


def pages():
    """{name key: chittorgarh IPO page URL} for every current mainboard and SME IPO."""
    out = {}
    for u in LISTS:
        for url, slug in re.findall(r'href="(https://www\.chittorgarh\.com/ipo/([a-z0-9-]+)/\d+/)"', requests.get(u, headers=WEB, timeout=20).text):
            out.setdefault(_key(slug.replace("-", " ")), url)
    return out


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
    """Sections of one chittorgarh IPO page, picked by the words in each table's header or first column."""
    tables = pd.read_html(io.StringIO(requests.get(url, headers=WEB, timeout=20).text))
    words = lambda t: " ".join(map(str, [*t.columns, *t.iloc[:, 0]])).lower()
    find = lambda *w: next((t for t in tables if all(x.lower() in words(t) for x in w)), None)
    return {"issue": find("price band"), "size": find("total issue size"), "lots": find("application", "lots"),
            "financials": find("period ended", "assets"), "kpi": find("kpi"), "valuation": find("valuation metric"),
            "holding": find("promoter and promoter group", "pre ipo"), "objects": find("issue objects"),
            "reviews": find("review by"), "url": url}


def _kv(t):
    return {} if t is None else {str(r.iloc[0]).strip().rstrip(":").strip(): r.iloc[1] for _, r in t.iterrows()}


def years(fin):
    """chittorgarh's financials (one column per period) -> one row per FULL fiscal year, oldest first, numeric.
    A '30 Jun 2026' column is a part-year and would fake a collapse. The year-end is the day+month that repeats most
    across the columns ('31 Mar' for most companies, '31 Dec' for calendar-year ones); ties go to 31 Mar."""
    f = fin.set_index(fin.columns[0]).T
    ends = [m.group(1) for p in f.index if (m := re.fullmatch(r"(\d{1,2} \w{3}) \d{4}", str(p).strip()))]
    if not ends:
        return f.iloc[0:0]
    end = max(set(ends), key=lambda e: (ends.count(e), e == "31 Mar"))
    f = f[[str(p).strip().startswith(end + " ") for p in f.index]]
    return f.apply(lambda col: col.map(num)).iloc[::-1]  # the page lists newest first


def metrics(row, gmp, pg):
    """Flat metrics for the rules. Anything a source didn't give is None, which makes rules using it fail."""
    hi = num(str(row.get("issuePrice") or row.get("priceBand") or "").split("to")[-1])
    m = {k: None for k in METRICS}
    m |= {"ipo_price": hi, "ipo_is_sme": int(row.get("series") == "SME"),
          "ipo_days_to_close": (datetime.strptime(row["issueEndDate"], "%d-%b-%Y").date() - datetime.now().date()).days}
    if size := _kv(pg.get("size")).get("Total Issue Size"):
        cr = re.search(r"₹\s*([\d,.]+)\s*Cr", str(size))
        m["ipo_issue_cr"] = num(cr.group(1)) if cr else None
    if gmp and gmp["gmp"] is not None:
        m["ipo_gmp"] = gmp["gmp"]
        m["ipo_gmp_pct"] = round(gmp["gmp"] / hi * 100, 2) if hi else None
    if (lots := pg.get("lots")) is not None:  # the smallest retail / individual application
        first = lots[lots.iloc[:, 0].astype(str).str.contains(r"Retail|IND", case=False)]
        m["ipo_min_amount"] = num(first.iloc[0, -1]) if len(first) else None
    fy_month = None
    if pg.get("financials") is not None and len(f := years(pg["financials"])) >= 1:
        fy_month = str(f.index[-1]).split()[1]  # 'Mar' / 'Dec': which KPI column is the full year
        col = lambda *names: next((f[c] for c in f.columns if any(n.lower() in str(c).lower() for n in names)), None)
        rev, pat = col("Revenue", "Total Income"), col("Profit After Tax", "PAT")
        ebitda, worth, debt = col("EBITDA"), col("Net Worth"), col("Total Borrowing")
        if rev is not None and pat is not None:
            m |= {"ipo_revenue_cr": rev.iloc[-1], "ipo_pat_cr": pat.iloc[-1]}
            if rev.iloc[-1]:
                m["ipo_pat_margin"] = round(pat.iloc[-1] / rev.iloc[-1] * 100, 2)
                if ebitda is not None and ebitda.iloc[-1] == ebitda.iloc[-1]:
                    m["ipo_ebitda_margin"] = round(ebitda.iloc[-1] / rev.iloc[-1] * 100, 2)
            if len(f) >= 2 and rev.iloc[-2]:
                m["ipo_revenue_growth"] = round((rev.iloc[-1] / rev.iloc[-2] - 1) * 100, 2)
            if len(f) >= 2 and pat.iloc[-2] and pat.iloc[-2] > 0:
                m["ipo_pat_growth"] = round((pat.iloc[-1] / pat.iloc[-2] - 1) * 100, 2)
            if worth is not None and worth.iloc[-1] and worth.iloc[-1] > 0:
                m["ipo_roe"] = round(pat.iloc[-1] / worth.iloc[-1] * 100, 2)  # full-year profit / net worth
        if worth is not None and worth.iloc[-1] and worth.iloc[-1] > 0:  # no borrowing listed = debt-free
            d = debt.iloc[-1] if debt is not None and debt.iloc[-1] == debt.iloc[-1] else 0.0
            m["ipo_debt_equity"] = round(d / worth.iloc[-1], 2)
    k = pg.get("kpi")  # ratios from the full-year column ('Mar 31, 2026'), not a quarter ('Jun 30, 2026')
    if k is not None and len(k.columns) > 1:
        c = next((c for c in k.columns[1:] if fy_month and str(c).startswith(fy_month)), k.columns[-1])
        kpi = dict(zip(k.iloc[:, 0].astype(str).str.strip(), k[c]))
        pick = lambda *names: next((num(v) for n in names for key, v in kpi.items() if key.lower() == n.lower() and num(v) is not None), None)
        m["ipo_roce"] = pick("ROCE")
        m["ipo_roe"] = m["ipo_roe"] if m["ipo_roe"] is not None else pick("ROE", "RoNW")
        m["ipo_debt_equity"] = m["ipo_debt_equity"] if m["ipo_debt_equity"] is not None else pick("Debt/Equity", "Debt to Equity")
    if (v := pg.get("valuation")) is not None:  # post-issue P/E, else pre-issue; a loss ('-ve') leaves it None
        pe = v[v.iloc[:, 0].astype(str).str.startswith("P/E")]
        m["ipo_pe"] = next((num(x) for x in (pe.iloc[0, -1], pe.iloc[0, 1]) if num(x) is not None and num(x) > 0), None) if len(pe) else None
    if (h := pg.get("holding")) is not None:
        prom = h[h.iloc[:, 0].astype(str).str.contains("Promoter")]
        m["ipo_promoter_post_pct"] = num(prom.iloc[0, -1]) if len(prom) else None
    if (r := pg.get("reviews")) is not None:  # brokers' published calls on the issue
        b = r[r.iloc[:, 0].astype(str).str.contains("Broker")]
        if len(b):
            get = lambda c: int(num(b.iloc[0][c]) or 0) if c in b.columns else 0
            m |= {"ipo_broker_subscribe": get("Subscribe") + get("May Apply"), "ipo_broker_neutral": get("Neutral"),
                  "ipo_broker_avoid": get("Avoid")}
    return m


def one(row, gmps, urls):
    """Everything about one IPO; each source fails on its own (e.g. BSE-only SME issues have no NSE bid book)."""
    gk, pk = _match(row["companyName"], [g["key"] for g in gmps]), _match(row["companyName"], list(urls))
    gmp = next((g for g in gmps if g["key"] == gk), None)
    errors, sub, pg = {}, {}, {}
    try:
        sub = subscription(row["symbol"]) if row.get("status") == "Active" else {}
    except Exception as ex:
        errors["subscription"] = f"{type(ex).__name__}: {ex}"
    try:
        pg = page(urls[pk]) if pk else {}
    except Exception as ex:
        errors["financials"] = f"{type(ex).__name__}: {ex}"
    if not gmp:
        errors["gmp"] = "no GMP on investorgain.com"
    if not pk:
        errors["financials"] = errors.get("financials") or "no page on chittorgarh.com"
    return {"row": row, "gmp": gmp, "sub": sub, "page": pg, "metrics": metrics(row, gmp, pg) | {
        f"ipo_sub_{k}": sub.get(k) for k in ("total", "qib", "nii", "retail")}, "errors": errors}


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
    try:
        urls = pages()
    except Exception:
        urls = {}
    with ThreadPoolExecutor(4) as pool:  # shortcut: 4 at a time keeps the sites from throttling us; raise if lists grow
        return list(pool.map(lambda r: one(r, gmps, urls), rows))


if __name__ == "__main__":  # offline self-check of the parsers, on tables shaped like chittorgarh's
    assert num("₹1,94,480") == 194480 and num("33.67%") == 33.67 and num("Approx ₹178 Crores") == 178 and num("₹-") is None
    assert _key("Tonbo Imaging India IPOO") == _key("tonbo-imaging-india-ipo".replace("-", " ")) == _key("Tonbo Imaging (India) Limited")
    assert _key("Shellz India BSE SMEO") == "shellz"
    row = {"symbol": "X", "series": "EQ", "issuePrice": "Rs.208 to Rs.220", "issueEndDate": "05-Oct-2099"}
    fin = pd.DataFrame({"Period Ended": ["Assets", "Total Income", "Profit After Tax", "EBITDA", "NET Worth", "Total Borrowing"],
                        "30 Jun 2026": ["400", "7.49", "1.83", "2", "200", "90"], "31 Mar 2026": ["380", "344.13", "24.98", "51.6", "190", "95"],
                        "31 Mar 2025": ["300", "324.86", "23.64", "40", "150", "80"]})
    pg = {"financials": fin, "kpi": pd.DataFrame({"KPI": ["ROE", "RoNW", "ROCE"], "Mar 31, 2026": ["33.67%", "30%", "28.02%"]}),
          "valuation": pd.DataFrame({"Valuation Metric": ["EPS (₹)", "P/E (x)"], "Pre IPO": ["12.61", "17.45"], "Post IPO": ["10", "-ve"]}),
          "size": pd.DataFrame({0: ["Total Issue Size"], 1: ["33,20,07,155 shares (agg. up to ₹5,012 Cr)"]}),
          "lots": pd.DataFrame({"Application": ["Retail (Min)", "Retail (Max)"], "Lots": [1, 13], "Amount": ["₹14,960", "₹1,94,480"]}),
          "holding": pd.DataFrame({"Category": ["Promoter and Promoter Group"], "Pre IPO": ["73.42%"], "Post IPO": ["49.40%"]}),
          "reviews": pd.DataFrame({"Review By": ["Brokers"], "Subscribe": [2], "May Apply": [1], "Neutral": [4], "Avoid": [0]})}
    m = metrics(row, {"gmp": 20.0}, pg)
    assert m["ipo_gmp_pct"] == 9.09 and m["ipo_roe"] == 13.15 and m["ipo_roce"] == 28.02 and m["ipo_pe"] == 17.45  # ROE = 24.98/190
    assert m["ipo_revenue_cr"] == 344.13 and m["ipo_revenue_growth"] == 5.93 and m["ipo_pat_growth"] == 5.67  # June quarter ignored
    assert m["ipo_debt_equity"] == 0.5 and m["ipo_pat_margin"] == 7.26 and m["ipo_ebitda_margin"] == 14.99
    assert m["ipo_issue_cr"] == 5012 and m["ipo_min_amount"] == 14960 and m["ipo_promoter_post_pct"] == 49.4
    assert (m["ipo_broker_subscribe"], m["ipo_broker_neutral"], m["ipo_broker_avoid"]) == (3, 4, 0)
    dec = pd.DataFrame({"Period Ended": ["Total Income", "Profit After Tax", "NET Worth"], "30 Jun 2026": ["1139", "148", "1034"],
                        "31 Dec 2025": ["2023.59", "237.87", "975.25"], "31 Dec 2024": ["1861.16", "195.16", "860.95"]})
    assert list(years(dec).index) == ["31 Dec 2024", "31 Dec 2025"]  # calendar-year company; the June half-year is dropped
    assert metrics(row, None, {"financials": dec})["ipo_debt_equity"] == 0.0  # no borrowing row = debt-free
    assert _match("Zetwerk Manufacturing Businesses Limited", ["zetwerk", "zen tech"]) == "zetwerk"
    print("ok")
