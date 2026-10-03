"""Mutual funds: every open-ended scheme from AMFI, NAV history from mfapi.in, benchmarks from Yahoo. Pure data.

Metrics come from NAV alone (returns, risk, risk-adjusted return, beta/alpha vs a benchmark), so they cover every
fund equally. Benchmarks are price indices (no dividends), which flatters funds by roughly 1-1.5%/yr versus the
TRI their factsheets use; the Smallcap 250 benchmark is an index fund's NAV (total return, minus a small fee).
Expense ratio, AUM and portfolio are not in these free sources.
"""
import io
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
import yfinance as yf

AMFI = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI = "https://api.mfapi.in/mf/{}"
RF = 6.5  # ponytail: fixed risk-free % (~Indian T-bill yield) for Sharpe/alpha; pull the live 91-day T-bill rate if it matters
BENCHMARKS = {
    "NIFTY 50": ("yf", "^NSEI"), "NIFTY 100": ("yf", "^CNX100"), "NIFTY 200": ("yf", "^CNX200"),
    "NIFTY 500": ("yf", "^CRSLDX"), "NIFTY Next 50": ("yf", "^NSMIDCP"), "NIFTY Midcap 150": ("yf", "NIFTYMIDCAP150.NS"),
    "NIFTY Smallcap 250 (index fund)": ("mf", 147623), "NIFTY Bank": ("yf", "^NSEBANK"), "NIFTY IT": ("yf", "^CNXIT"),
}
# category words -> the benchmark SEBI-style for that category; anything else gets NIFTY 500
DEFAULT_BENCH = [("Large & Mid", "NIFTY 200"), ("Large Cap", "NIFTY 100"), ("Mid Cap", "NIFTY Midcap 150"),
                 ("Small Cap", "NIFTY Smallcap 250 (index fund)"), ("Bank", "NIFTY Bank"), ("Financial", "NIFTY Bank"),
                 ("Technology", "NIFTY IT"), ("Index Funds", "NIFTY 50")]
METRICS = ["mf_ret_1y", "mf_cagr_3y", "mf_cagr_5y", "mf_excess_1y", "mf_excess_3y", "mf_excess_5y", "mf_vol_3y",
           "mf_max_dd_3y", "mf_sharpe_3y", "mf_sortino_3y", "mf_beta_3y", "mf_alpha_3y", "mf_age_years"]
WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}


GROUPS = [("ETF", "ETF"), ("Index Funds", "Index"), ("FoF", "Fund of Funds"), ("Fund of Funds", "Fund of Funds"),
          ("Equity", "Equity"), ("Hybrid", "Hybrid"), ("Debt", "Debt"), ("Solution", "Solution"), ("Children", "Solution"),
          ("Life Cycle", "Solution")]
SAME = [("Balanced Advantage", "Balanced Advantage"), ("Dynamic Asset Allocation", "Balanced Advantage"),
        ("Multi Asset", "Multi Asset Allocation"), ("ELSS", "ELSS (tax saver)"), ("Sectoral", "Sectoral / Thematic"),
        ("Thematic", "Sectoral / Thematic"), ("Ultra Short", "Ultra Short Duration"), ("Equity Savings", "Equity Savings"),
        ("Domestic", "Domestic"), ("Overseas", "Overseas"), ("Child", "Children's")]


def clean_category(raw):
    """AMFI is mid-rename ('Equity Scheme - Large Cap Fund' and 'Equity Schemes - Large Cap Fund' both live):
    -> one label like 'Equity · Large Cap'."""
    raw = raw.replace("â", "'").replace("  ", " ")
    head, _, sub = raw.partition(" - ")
    # group from the head ('Hybrid Scheme - Equity Savings' is hybrid), else from anywhere ('Other Scheme - Index Funds')
    group = next((g for word, g in GROUPS if word.lower() in head.lower()), None) or \
        next((g for word, g in GROUPS if word.lower() in raw.lower()), "Other")
    sub = sub.strip() or raw
    sub = next((s for word, s in SAME if word.lower() in sub.lower()), sub)
    sub = re.sub(r"\s*\bFunds?\b\s*$", "", sub).strip() or raw
    return f"{group} · {'All' if sub.lower() == group.lower() else sub}"


def funds():
    """Live Growth-option schemes (NAV within 10 days of the newest) with a clean category and Direct/Regular plan."""
    df = schemes()
    d = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    df = df[d >= d.max() - pd.Timedelta(days=10)].copy()
    name, opt, plan = df["name"].str.lower(), df["option"].str.lower(), df["plan"].str.lower()
    growth = opt.str.contains("growth") | ((opt == "") & name.str.contains("growth") & ~name.str.contains("idcw|dividend"))
    df["plan"] = np.where(plan.str.startswith("direct") | ((plan == "") & name.str.contains("direct")), "Direct", "Regular")
    df["category"] = df["category"].map(clean_category)
    return df[growth].drop(columns=["option"]).drop_duplicates("code").reset_index(drop=True)


def schemes():
    """All open-ended schemes as AMFI lists them: code, name, raw category, plan, option, latest NAV and its date."""
    text = requests.get(AMFI, headers=WEB, timeout=30).text
    rows, cat = [], None
    for line in text.splitlines():
        if m := re.match(r"\s*Open Ended Schemes\s*\((.+)\)\s*$", line):
            cat = m.group(1).strip()
        elif re.match(r"\s*(Close|Interval) Ended Schemes", line):
            cat = None
        elif cat and line.count(";") >= 7:
            p = line.split(";")
            if p[0].strip().isdigit():
                rows.append({"code": int(p[0]), "name": p[3].strip(), "category": cat, "plan": p[4].strip(),
                             "option": p[5].strip(), "nav": pd.to_numeric(p[6], errors="coerce"), "date": p[7].strip()})
    return pd.DataFrame(rows)


def default_benchmark(category):
    return next((b for words, b in DEFAULT_BENCH if words.lower() in category.lower()), "NIFTY 500")


def nav(code):
    d = requests.get(MFAPI.format(code), timeout=30).json()["data"]
    s = pd.Series({pd.to_datetime(x["date"], format="%d-%m-%Y"): float(x["nav"]) for x in d}).sort_index()
    return s[s > 0]


def benchmark(name, period="max"):
    kind, ref = BENCHMARKS[name]
    if kind == "mf":
        return nav(ref)
    s = yf.Ticker(ref).history(period=period)["Close"]
    return s.set_axis(s.index.tz_localize(None).normalize())


def _at(s, years):
    """Value `years` before the last date (last known value on or before it); None if history is shorter."""
    start = s.index[-1] - pd.DateOffset(years=years)
    return None if s.index[0] > start + pd.Timedelta(days=7) else s[:start].iloc[-1] if len(s[:start]) else s.iloc[0]


def cagr(s, years):
    a = _at(s, years)
    return None if a is None else round(((s.iloc[-1] / a) ** (1 / years) - 1) * 100, 2)


def metrics(s, bench):
    """NAV series (+ benchmark series) -> flat mf_* metrics. 3-year risk figures use daily returns."""
    m = {k: None for k in METRICS}
    if len(s) < 30:
        return m
    m["mf_age_years"] = round((s.index[-1] - s.index[0]).days / 365.25, 1)
    for y, k in ((1, "1y"), (3, "3y"), (5, "5y")):
        m[f"mf_{'ret' if y == 1 else 'cagr'}_{k}"] = f = cagr(s, y)
        b = cagr(bench, y) if bench is not None and len(bench) else None
        m[f"mf_excess_{k}"] = None if f is None or b is None else round(f - b, 2)
    w = s[s.index >= s.index[-1] - pd.DateOffset(years=3)]
    if m["mf_cagr_3y"] is None or len(w) < 200:
        return m
    r = w.pct_change().dropna()
    vol = r.std() * np.sqrt(252) * 100
    down = r[r < 0].std() * np.sqrt(252) * 100
    m |= {"mf_vol_3y": round(vol, 2), "mf_max_dd_3y": round((w / w.cummax() - 1).min() * 100, 2),
          "mf_sharpe_3y": round((m["mf_cagr_3y"] - RF) / vol, 2) if vol else None,
          "mf_sortino_3y": round((m["mf_cagr_3y"] - RF) / down, 2) if down else None}
    if bench is not None and len(bench):
        both = pd.concat([w, bench], axis=1, join="inner").pct_change().dropna()  # same trading days only
        if len(both) > 200 and both.iloc[:, 1].var():
            beta = both.cov().iloc[0, 1] / both.iloc[:, 1].var()
            b3 = cagr(bench, 3)
            m["mf_beta_3y"] = round(beta, 2)
            m["mf_alpha_3y"] = None if b3 is None else round(m["mf_cagr_3y"] - (RF + beta * (b3 - RF)), 2)  # Jensen's alpha
    return m


def rank(funds, bench_name, progress=None):
    """[{code, name, metrics}] for every fund (rows of schemes()), measured against one benchmark. Parallel fetch."""
    bench = benchmark(bench_name)
    done = [0]

    def one(f):
        try:
            out = {"code": f["code"], "name": f["name"], "metrics": metrics(nav(f["code"]), bench), "error": None}
        except Exception as ex:
            out = {"code": f["code"], "name": f["name"], "metrics": {k: None for k in METRICS}, "error": f"{type(ex).__name__}"}
        done[0] += 1
        if progress:
            progress(done[0] / len(funds), f["name"])
        return out

    with ThreadPoolExecutor(16) as pool:
        return list(pool.map(one, funds.to_dict("records")))


def growth(series, years=None, base=10000):
    """{name: series} -> each rebased to `base` from the latest common start (or `years` back), for a fair chart."""
    s = {k: v for k, v in series.items() if v is not None and len(v)}
    start = max(v.index[0] for v in s.values())
    if years:
        start = max(start, max(v.index[-1] for v in s.values()) - pd.DateOffset(years=years))
    return {k: v[v.index >= start] / v[v.index >= start].iloc[0] * base for k, v in s.items()}


if __name__ == "__main__":  # offline self-check on synthetic NAVs
    idx = pd.bdate_range("2019-01-01", "2026-01-01")
    fund = pd.Series(100 * 1.12 ** ((idx - idx[0]).days / 365.25), index=idx)    # 12%/yr, no volatility
    bench = pd.Series(100 * 1.10 ** ((idx - idx[0]).days / 365.25), index=idx)   # 10%/yr
    m = metrics(fund, bench)
    assert abs(m["mf_cagr_3y"] - 12) < 0.05 and abs(m["mf_excess_3y"] - 2) < 0.1 and m["mf_max_dd_3y"] == 0, m
    noisy = fund * (1 + 0.01 * np.sin(np.arange(len(idx))))
    m2 = metrics(noisy, noisy)
    assert m2["mf_beta_3y"] == 1.0 and abs(m2["mf_alpha_3y"]) < 0.01 and m2["mf_vol_3y"] > 0 and m2["mf_max_dd_3y"] < 0
    assert metrics(fund[-300:], bench)["mf_cagr_3y"] is None  # too young for 3 years
    g = growth({"a": fund, "b": bench[-500:]})
    assert all(abs(v.iloc[0] - 10000) < 1e-6 for v in g.values()) and g["a"].index[0] == bench.index[-500]
    assert clean_category("Equity Scheme - Large Cap Fund") == clean_category("Equity Schemes - Large Cap Fund") == "Equity · Large Cap"
    assert clean_category("Hybrid Scheme - Equity Savings") == "Hybrid · Equity Savings"
    assert clean_category("Equity Schemes - ELSS- Tax Saver Fund") == clean_category("Equity Scheme - ELSS") == "Equity · ELSS (tax saver)"
    print("ok")
