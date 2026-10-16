"""Commodities and forex: global futures from Yahoo (COMEX / NYMEX / ICE, quoted in USD), with an approximate rupee price.

MCX has no free feed, so these are the international contracts MCX prices follow. The rupee figure is the USD
price x USD/INR, converted to the unit MCX quotes in; it leaves out import duty, GST and the local premium, so
MCX trades higher (gold and silver most of all). Verdicts come from the [commodity] section of rules.toml and
use the same daily metrics as shares (close, ema_*, rsi, macd_*, supertrend_dir, sig_*).
Forex pairs are spot rates from Yahoo (BASEQUOTE: price of 1 BASE in QUOTE) and use the same rules section.
"""
import pandas as pd
import yfinance as yf

import data
import signals

OZ = 31.1035  # grams in a troy ounce
# symbol -> (name, unit of the USD quote, USD quote -> rupee unit multiplier, rupee unit). Tickers: data.COMMODITY_YF
ITEMS = {
    "GOLD": ("Gold", "$/oz", 10 / OZ, "₹/10 g"),
    "SILVER": ("Silver", "$/oz", 1000 / OZ, "₹/kg"),
    "PLATINUM": ("Platinum", "$/oz", 1 / OZ, "₹/g"),
    "CRUDEOIL": ("Crude oil (WTI)", "$/bbl", 1, "₹/bbl"),
    "BRENT": ("Brent crude", "$/bbl", 1, "₹/bbl"),
    "NATURALGAS": ("Natural gas", "$/mmBtu", 1, "₹/mmBtu"),
    "COPPER": ("Copper", "$/lb", 2.20462, "₹/kg"),
    "ALUMINIUM": ("Aluminium", "$/tonne", 0.001, "₹/kg"),
}
FOREX = {  # symbol -> name. Tickers: data.FOREX_YF
    "USDINR": "US dollar / rupee", "EURINR": "Euro / rupee", "GBPINR": "Pound / rupee", "JPYINR": "Yen / rupee",
    "EURUSD": "Euro / US dollar", "GBPUSD": "Pound / US dollar", "USDJPY": "US dollar / yen", "AUDUSD": "Aussie / US dollar",
    "USDCHF": "US dollar / Swiss franc", "USDCAD": "US dollar / Canadian dollar",
}


def metrics(d, s):
    """Daily candles -> the flat metric dict the rules engine reads."""
    frame = data.indicators(d, s)
    c = d["Close"]
    last, yr = float(c.iloc[-1]), d.tail(252)
    back = lambda n: (last / float(c.iloc[-n]) - 1) * 100 if len(c) >= n else None
    m = {"close": last, "price": last, **frame.iloc[-1].to_dict(), **signals.daily(d, frame),
         "change_pct": back(2), "ret_1w": back(6), "ret_1m": back(22), "ret_3m": back(64),
         "high_52w": float(yr["High"].max()), "low_52w": float(yr["Low"].min()),
         "pct_from_52w_high": (last / float(yr["High"].max()) - 1) * 100, "mtf_1d": data.tf_bias(d)}
    if not d["Volume"].iloc[-1]:
        m["vol_ratio"] = None  # some contracts report no volume on Yahoo
    m |= signals.score(m)
    return {k: (None if v != v else round(float(v), 4)) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            for k, v in m.items()}


def scan():
    """Returns ([{symbol, kind, name, unit, inr_unit, inr, usdinr, metrics}], symbols that failed to load). kind: commodity | forex."""
    tickers = [data.COMMODITY_YF[k] for k in ITEMS] + [data.FOREX_YF[k] for k in FOREX]
    raw = yf.download(tickers, period="2y", interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=False)
    fx = raw["USDINR=X"]["Close"].dropna()
    usdinr = float(fx.iloc[-1]) if len(fx) else None
    s = data.load_settings()
    rows, failed = [], []
    todo = [(k, "commodity", *v) for k, v in ITEMS.items()] + [(k, "forex", n, f"{k[3:]} per {k[:3]}", None, "") for k, n in FOREX.items()]
    for sym, kind, name, unit, mult, inr_unit in todo:
        try:
            d = raw[data.yf_symbol(sym, None)].dropna(subset=["Close"])
            if len(d) < 210:
                raise ValueError("not enough history")
            m = metrics(d, s)
        except Exception:
            failed.append(sym)
            continue
        rows.append({"symbol": sym, "kind": kind, "name": name, "unit": unit, "inr_unit": inr_unit, "usdinr": usdinr,
                     "inr": usdinr and mult and round(m["close"] * usdinr * mult, 2), "metrics": m})
    return rows, failed
