"""Market-wide scanners from NSE's public live-analysis endpoints. Each returns a pandas DataFrame, newest data first."""
import io

import pandas as pd

import data
from data import NSE, nse

MOVER_GROUPS = {"F&O stocks": "FOSec", "NIFTY 50": "NIFTY", "BANK NIFTY": "BANKNIFTY", "NIFTY NEXT 50": "NIFTYNEXT50",
                "All securities": "allSec"}
UNIVERSES = {  # scanner universes: NSE's public index CSVs, and the F&O master list
    "NIFTY 50": "ind_nifty50list.csv", "NIFTY BANK": "ind_niftybanklist.csv", "NIFTY NEXT 50": "ind_niftynext50list.csv",
    "NIFTY IT": "ind_niftyitlist.csv", "NIFTY AUTO": "ind_niftyautolist.csv", "NIFTY PHARMA": "ind_niftypharmalist.csv",
    "F&O stocks": None,
}


def volume_shockers():
    """Stocks trading far above their usual volume today."""
    df = pd.DataFrame(nse("live-analysis-volume-gainers")["data"])
    df["x_avg"] = df["volume"] / df["week1AvgVolume"].where(df["week1AvgVolume"] > 0)
    return (df.rename(columns={"companyName": "name", "pChange": "change_pct", "week1AvgVolume": "avg_volume_1w"})
            [["symbol", "name", "ltp", "change_pct", "volume", "avg_volume_1w", "x_avg"]]
            .sort_values("x_avg", ascending=False, ignore_index=True))


def most_active(by="value"):
    """Most traded by value (where the money went) or by volume."""
    df = pd.DataFrame(nse(f"live-analysis-most-active-securities?index={by}")["data"])
    df["value_cr"] = df["totalTradedValue"] / 1e7
    return (df.rename(columns={"lastPrice": "ltp", "pChange": "change_pct", "totalTradedVolume": "volume"})
            [["symbol", "ltp", "change_pct", "volume", "value_cr", "yearHigh", "yearLow"]])


def most_bought():
    """Closest public proxy for 'most bought': highest traded value today among stocks that are up."""
    df = most_active("value")
    return df[df["change_pct"] > 0].reset_index(drop=True)


def movers(kind="gainers", group="F&O stocks"):
    raw = nse(f"live-analysis-variations?index={'gainers' if kind == 'gainers' else 'loosers'}")
    df = pd.DataFrame(raw[MOVER_GROUPS[group]]["data"])
    df["value_cr"] = df["turnover"] / 100  # NSE reports this turnover in ₹ lakh
    return (df.rename(columns={"perChange": "change_pct", "prev_price": "prev_close", "trade_quantity": "volume"})
            [["symbol", "ltp", "change_pct", "prev_close", "volume", "value_cr"]])


def oi_spurts():
    """F&O underlyings with the biggest jump in open interest."""
    df = pd.DataFrame(nse("live-analysis-oi-spurts-underlyings")["data"])
    return (df.rename(columns={"avgInOI": "oi_change_pct", "changeInOI": "oi_change", "latestOI": "oi", "underlyingValue": "price"})
            [["symbol", "price", "oi", "oi_change", "oi_change_pct", "volume"]]
            .sort_values("oi_change_pct", ascending=False, ignore_index=True))


def active_options(by="volume"):
    """Most traded option contracts today."""
    df = pd.DataFrame(nse("snapshot-derivatives-equity?index=contracts&limit=50")[by]["data"])
    df = df[df["instrumentType"].str.startswith("OPT")]
    df["contract"] = df.apply(lambda r: f"{r['underlying']} {r['strikePrice']:g} {'CE' if r['optionType'] == 'Call' else 'PE'}", axis=1)
    return (df.rename(columns={"expiryDate": "expiry", "lastPrice": "ltp", "pChange": "change_pct",
                               "numberOfContractsTraded": "contracts", "openInterest": "oi", "underlyingValue": "spot"})
            [["contract", "expiry", "ltp", "change_pct", "contracts", "oi", "spot"]].reset_index(drop=True))


def sectors():
    """Sector indices: returns over 1 day / 1 week / 1 month / 1 year and strength relative to NIFTY 50."""
    rows = nse("allIndices")["data"]
    nifty = next(r for r in rows if r["index"] == "NIFTY 50")
    pct = lambda r: {"1D": r["percentChange"], "1W": (r["last"] / r["oneWeekAgoVal"] - 1) * 100 if r.get("oneWeekAgoVal") else None,
                     "1M": r["perChange30d"], "1Y": r["perChange365d"] or None}  # NSE sends 0 when there is no 1-year history
    base = pct(nifty)
    out = []
    for r in rows:
        if r.get("key") != "SECTORAL INDICES":
            continue
        p = pct(r)
        out.append({"sector": r["index"].replace("NIFTY ", "").title(), "last": r["last"], **p,
                    **{f"rs_{k}": (p[k] - base[k]) if p[k] is not None and base[k] is not None else None for k in p},
                    "adv": int(r.get("advances") or 0), "dec": int(r.get("declines") or 0)})
    return pd.DataFrame(out).sort_values("1D", ascending=False, ignore_index=True), base


def events(days=30):
    """Upcoming corporate events (results, board meetings) from NSE's event calendar."""
    from datetime import date
    today = date.today()
    df = pd.DataFrame(data.events_calendar())
    if df.empty:
        return df
    df["days_away"] = df["when"].map(lambda d: (d - today).days)
    df = df[(df["days_away"] >= 0) & (df["days_away"] <= days)]
    return (df.rename(columns={"bm_desc": "details"})[["when", "days_away", "symbol", "company", "purpose", "details"]]
            .sort_values(["when", "symbol"], ignore_index=True))


_INDUSTRY = {}


def industries():
    """{symbol: industry} from NSE's NIFTY 500 list (cached). Stocks outside the index are simply missing."""
    if not _INDUSTRY:
        r = NSE.get("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv", timeout=10)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        _INDUSTRY.update(zip(df["Symbol"], df["Industry"]))
    return _INDUSTRY


_LOTS = {}


def lot_size(symbol):
    """F&O lot size for the nearest contract month, from NSE's official lot-size file (cached)."""
    if not _LOTS:
        r = NSE.get("https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", timeout=10)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        month = df.columns[2]
        for sym, lot in zip(df["SYMBOL"].astype(str).str.strip(), pd.to_numeric(df[month].astype(str).str.strip(), errors="coerce")):
            if lot == lot:
                _LOTS[sym] = int(lot)
    return _LOTS.get(symbol)


def universe(name="NIFTY 50"):
    """Symbols to scan."""
    if UNIVERSES[name] is None:
        return list(nse("master-quote"))
    r = NSE.get(f"https://nsearchives.nseindia.com/content/indices/{UNIVERSES[name]}", timeout=10)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))["Symbol"].dropna().tolist()
