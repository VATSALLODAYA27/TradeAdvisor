"""Free data sources for the desk: NSE, Yahoo Finance, FRED, Google News. Every fetch raises on failure; callers decide."""
import io
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import pandas as pd
import requests
import yfinance as yf

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"
NSE = requests.Session()
NSE.headers.update({"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"})
NIFTY500 = "^CRSLDX"
ASSETS = {"Indian Equity": "^CRSLDX", "International Equity": "MON100.NS", "Gold": "GOLDBEES.NS", "Bonds": "GILT5YBEES.NS"}
HEDGE = ["GOLDBEES.NS", "SILVERBEES.NS"]


def nse_api(path, tries=3):
    """NSE JSON API. It wants fresh site cookies; on 401/403 load the home page and retry."""
    for k in range(tries):
        r = NSE.get(f"https://www.nseindia.com/api/{path}", timeout=15)
        if r.status_code in (401, 403) and k < tries - 1:
            NSE.cookies.clear()
            NSE.get("https://www.nseindia.com/", headers={"Accept": "text/html"}, timeout=15)
            time.sleep(1 + k)
            continue
        r.raise_for_status()
        return r.json()


def nifty500():
    """[{symbol, company, industry}] from NSE's official constituents file."""
    r = NSE.get("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv", timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text)).dropna(subset=["Symbol"])
    return [{"symbol": s, "company": c, "industry": i} for s, c, i in zip(df["Symbol"], df["Company Name"], df["Industry"])]


def candles(tickers, period="2y"):
    """{ticker: daily OHLCV} for Yahoo tickers, one batched download."""
    raw = yf.download(tickers, period=period, interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=False)
    out = {}
    for t in tickers:
        try:
            d = raw[t].dropna(subset=["Close"])
            if len(d):
                out[t] = d
        except KeyError:
            pass
    return out


def delivery(days=10):
    """Delivery % per NSE symbol for the last `days` sessions, from NSE's full bhavcopy: DataFrame index date, columns symbol."""
    frames, day = {}, date.today()
    for _ in range(days * 2 + 6):
        if len(frames) >= days:
            break
        r = NSE.get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv", timeout=15)
        if r.ok and r.text.startswith("SYMBOL"):
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = df.columns.str.strip()
            df = df[df["SERIES"].str.strip() == "EQ"]
            frames[pd.to_datetime(df["DATE1"].iloc[0].strip())] = pd.to_numeric(df["DELIV_PER"], errors="coerce").set_axis(df["SYMBOL"].str.strip())
        day -= timedelta(days=1)
    return pd.DataFrame(frames).T.sort_index()


def fred(series):
    df = pd.read_csv(io.StringIO(requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=20).text))
    df = df[pd.to_numeric(df.iloc[:, 1], errors="coerce").notna()]
    return pd.Series(df.iloc[:, 1].astype(float).values, index=pd.to_datetime(df.iloc[:, 0]))


def headlines(company, days=30, n=20):
    """Google News for a company: [{title, source, date}] newest first."""
    url = f"https://news.google.com/rss/search?q={quote_plus(chr(34) + company + chr(34) + ' share')}&hl=en-IN&gl=IN&ceid=IN:en"
    root = ET.fromstring(requests.get(url, headers={"User-Agent": UA}, timeout=20).content)
    cut, out = datetime.now(timezone.utc) - timedelta(days=days), []
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        title, src = (it.findtext("title") or "").strip(), it.findtext("source") or ""
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        if title and when >= cut:
            out.append({"title": title, "source": src, "date": when.date().isoformat()})
    return sorted(out, key=lambda x: x["date"], reverse=True)[:n]


def filings(symbol, days=90, n=25):
    """NSE corporate announcements (board outcomes, results, auditor changes, rating actions...): [{subject, text, date}]."""
    rows = nse_api(f"corporate-announcements?index=equities&symbol={quote_plus(symbol)}") or []
    cut, out = datetime.now() - timedelta(days=days), []
    for r in rows:
        try:
            when = datetime.strptime(r["an_dt"], "%d-%b-%Y %H:%M:%S")
        except (KeyError, ValueError):
            continue
        if when >= cut:
            out.append({"subject": r.get("desc") or "", "text": (r.get("attchmntText") or "")[:400], "date": when.date().isoformat()})
    return out[:n]


def earnings(ticker):
    """Latest reported quarter vs consensus from Yahoo: {date, eps_estimate, eps_reported, surprise_pct} or None."""
    e = yf.Ticker(ticker).earnings_dates
    if e is None or e.empty:
        return None
    done = e.dropna(subset=["Reported EPS"])
    if done.empty:
        return None
    r = done.iloc[0]
    val = lambda x: None if pd.isna(x) else round(float(x), 2)
    return {"date": done.index[0].date().isoformat(), "eps_estimate": val(r["EPS Estimate"]), "eps_reported": val(r["Reported EPS"]),
            "surprise_pct": val(r["Surprise(%)"])}
