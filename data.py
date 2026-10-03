"""Free NSE/BSE data -> one flat dict of metrics. Rules in rules.toml refer to these keys."""
import json
import time
import numbers
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

import signals
import vatsal

INDEX_YF = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}

NSE = requests.Session()
NSE.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/option-chain",
})


def nse(path, tries=3):
    # ponytail: unofficial NSE endpoints, no auth; they break when NSE changes its site. Swap for a broker feed then.
    for attempt in range(tries):
        try:
            r = NSE.get(f"https://www.nseindia.com/api/{path}", timeout=10)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout):  # NSE often drops the first connection; retry
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


SETTINGS_FILE = Path(__file__).with_name("indicators.json")
DEFAULTS = {
    "ema": [20, 50, 200],       # metrics ema_20, ... drawn on the chart (Vatsal mode draws vatsal.emas instead)
    "sma": [],                  # metrics sma_<n>
    "rsi": 14,                  # rsi (daily), rsi_5m (5-min bars)
    "macd": [12, 26, 9],        # macd, macd_signal, macd_hist
    "atr": 14,                  # atr, atr_pct
    "bollinger": [20, 2],       # bb_upper, bb_mid, bb_lower, bb_pct_b
    "supertrend": [10, 3],      # supertrend, supertrend_dir (+1 up / -1 down)
    "volume_avg": 20,           # vol_ratio = today's volume / N-day average
    "orb_minutes": 15,          # orb_high, orb_low
    "vatsal": vatsal.DEFAULTS,  # Vatsal's indicator (vatsal.py)
    "option_pick": {            # which option to BUY (option_pick.py)
        "advisor": "options",   # whose verdict picks the side
        "ce_on": ["BULLISH", "BUY"],
        "pe_on": ["BEARISH", "SELL"],
        "target_delta": 0.5,    # 0.5 ~ ATM, 0.3 ~ OTM, 0.7 ~ ITM
        "min_oi": 100,          # open interest, in contracts
        "max_spread_pct": 5,    # (ask - bid) / mid
    },
}


def validate_settings(s):
    """Return cleaned settings or raise ValueError. Missing keys fall back to DEFAULTS."""
    s = {**DEFAULTS, **s}
    for sub in ("option_pick", "vatsal"):
        s[sub] = {**DEFAULTS[sub], **(s[sub] if isinstance(s[sub], dict) else {})}
    labels = lambda v: isinstance(v, list) and all(isinstance(x, str) and x for x in v)
    period = lambda v: isinstance(v, int) and not isinstance(v, bool) and 2 <= v <= 400
    mult = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 10
    checks = {
        "ema": lambda v: isinstance(v, list) and len(v) <= 6 and all(map(period, v)),
        "sma": lambda v: isinstance(v, list) and len(v) <= 6 and all(map(period, v)),
        "rsi": period, "atr": period, "volume_avg": period,
        "macd": lambda v: isinstance(v, list) and len(v) == 3 and all(map(period, v)) and v[0] < v[1],
        "bollinger": lambda v: isinstance(v, list) and len(v) == 2 and period(v[0]) and mult(v[1]),
        "supertrend": lambda v: isinstance(v, list) and len(v) == 2 and period(v[0]) and mult(v[1]),
        "orb_minutes": lambda v: v in (5, 10, 15, 30, 45, 60),
        "vatsal": lambda v: all(period(v[k]) for k in ("ema_filter", "fib_depth", "sd_swing", "sd_history"))
        and isinstance(v["liq_max_zones"], int) and 1 <= v["liq_max_zones"] <= 5000
        and isinstance(v["emas"], list) and 0 < len(v["emas"]) <= 6 and all(map(period, v["emas"]))
        and isinstance(v["fvg"], bool) and isinstance(v["fvg_show"], int) and 0 <= v["fvg_show"] <= 100
        and len(v["trigger"]) == 2 and all(map(period, v["trigger"])) and len(v["cross"]) == 2 and all(map(period, v["cross"]))
        and isinstance(v["cross_lookback"], int) and 0 <= v["cross_lookback"] <= 50
        and isinstance(v["signal_expiry"], int) and 0 <= v["signal_expiry"] <= 50 and isinstance(v["alternate"], bool)
        and mult(v["fib_deviation"]) and mult(v["sd_box_width"])
        and isinstance(v["fib_levels"], list) and all(isinstance(x, (int, float)) for x in v["fib_levels"]),
        "option_pick": lambda v: isinstance(v["advisor"], str) and labels(v["ce_on"]) and labels(v["pe_on"])
        and not set(v["ce_on"]) & set(v["pe_on"])
        and mult(v["target_delta"]) and v["target_delta"] < 1
        and isinstance(v["min_oi"], int) and v["min_oi"] >= 0
        and mult(v["max_spread_pct"]) and v["max_spread_pct"] <= 50,
    }
    hints = {
        "ema": "up to 6 whole-number periods, 2-400", "sma": "up to 6 whole-number periods, 2-400",
        "rsi": "a whole number 2-400", "atr": "a whole number 2-400", "volume_avg": "a whole number 2-400",
        "macd": "fast, slow, signal as whole numbers, fast smaller than slow",
        "bollinger": "period 2-400 and a multiplier above 0", "supertrend": "ATR period 2-400 and a multiplier above 0",
        "orb_minutes": "one of 5, 10, 15, 30, 45, 60",
        "vatsal": "trigger/cross EMA periods 2-400, lookback/expiry 0-50, deviation and box width above 0",
        "option_pick": "target delta between 0 and 1, min OI 0 or more, max spread 0-50%, and no verdict in both CE and PE lists",
    }
    for k, ok in checks.items():
        if not ok(s[k]):
            raise ValueError(f"{k} = {s[k]!r} is invalid: needs {hints[k]}")
    return {k: s[k] for k in DEFAULTS} | {"ema": sorted(set(s["ema"])), "sma": sorted(set(s["sma"]))}


def load_settings():
    return validate_settings(json.loads(SETTINGS_FILE.read_text())) if SETTINGS_FILE.exists() else dict(DEFAULTS)


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def supertrend(h, l, c, atr, mult):
    """Standard Supertrend (same rules as TradingView). Returns (line, direction +1 up / -1 down)."""
    hl2 = ((h + l) / 2).to_numpy()
    ub, lb, c = hl2 + mult * atr.to_numpy(), hl2 - mult * atr.to_numpy(), c.to_numpy()
    fub, flb, d = ub.copy(), lb.copy(), [1] * len(c)
    for i in range(1, len(c)):
        fub[i] = ub[i] if ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1] else fub[i - 1]
        flb[i] = lb[i] if lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1] else flb[i - 1]
        d[i] = (-1 if c[i] < flb[i] else 1) if d[i - 1] == 1 else (1 if c[i] > fub[i] else -1)
    line = [flb[i] if d[i] == 1 else fub[i] for i in range(len(c))]
    return pd.Series(line, index=h.index), pd.Series(d, index=h.index)


def indicators(d, s):
    """Every settings-driven indicator as a series. Metrics use the last row; the chart uses the whole series."""
    c, h, l, v = d["Close"], d["High"], d["Low"], d["Volume"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / s["atr"], adjust=False).mean()  # Wilder ATR, as on TradingView
    fast, slow, sig = s["macd"]
    macd = ema(c, fast) - ema(c, slow)
    signal = ema(macd, sig)
    bn, bk = s["bollinger"]
    mid, sd = c.rolling(bn).mean(), c.rolling(bn).std(ddof=0)
    st, st_dir = supertrend(h, l, c, tr.ewm(alpha=1 / s["supertrend"][0], adjust=False).mean(), s["supertrend"][1])
    return pd.DataFrame({
        **{f"ema_{n}": ema(c, n) for n in all_emas(s)},
        **{f"sma_{n}": c.rolling(n).mean() for n in s["sma"]},
        "rsi": rsi(c, s["rsi"]),
        "macd": macd, "macd_signal": signal, "macd_hist": macd - signal,
        "atr": atr, "atr_pct": atr / c * 100,
        "bb_upper": mid + bk * sd, "bb_mid": mid, "bb_lower": mid - bk * sd,
        "bb_pct_b": (c - (mid - bk * sd)) / (2 * bk * sd),
        "supertrend": st, "supertrend_dir": st_dir,
        "vol_ratio": v / v.shift().rolling(s["volume_avg"]).mean(),
    }, index=d.index)


def all_emas(s):
    """Standard EMA periods plus Vatsal's, so rules can use either set whichever view is on."""
    return sorted(set(s["ema"]) | set(s["vatsal"]["emas"]))


def metric_names(s):
    """Every metric key collect() can produce with these settings (for the rule builder's suggestions)."""
    import ipo  # ipo and mf import this module
    import mf
    ind = [*(f"ema_{n}" for n in all_emas(s)), *(f"sma_{n}" for n in s["sma"]), "rsi", "macd", "macd_signal", "macd_hist",
           "atr", "atr_pct", "bb_upper", "bb_mid", "bb_lower", "bb_pct_b", "supertrend", "supertrend_dir", "vol_ratio"]
    return {
        "Daily": ["close", *ind, "high_52w", "low_52w", "pct_from_52w_high", "ret_1m", "ret_3m"],
        "Timeframes & events": ["mtf_15m", "mtf_1h", "mtf_1d", "mtf_score", "mtf_aligned", "days_to_event"],
        "Signals": [*signals.KEYS, "sig_bull", "sig_bear", "sig_score", "resistance_20d", "support_20d"],
        "Vatsal": ["vs_bias", "vs_signal", "vs_signal_age", "vs_cross_age", "vs5m_bias", "vs5m_signal", "vs5m_signal_age",
                   *(f"fib_{str(x).replace('.', '')}" for x in s["vatsal"]["fib_levels"]),
                   "pivot_p", "pivot_r1", "pivot_r2", "pivot_r3", "pivot_s1", "pivot_s2", "pivot_s3",
                   "supply_bottom", "supply_top", "demand_top", "demand_bottom", "in_supply", "in_demand",
                   "fvg_bull_top", "fvg_bull_bottom", "fvg_bear_bottom", "fvg_bear_top", "in_fvg"],
        "Intraday": ["price", "vwap", "rsi_5m", "vol_ratio_5m", "day_change_pct", "day_high", "day_low", "orb_high", "orb_low"],
        "Fundamentals": ["pe", "pb", "roe", "debt_to_equity", "revenue_growth", "earnings_growth", "profit_margin", "market_cap_cr"],
        "Options": ["spot", "days_to_expiry", "pcr_oi", "max_pain", "atm_iv", "call_wall", "put_wall"],
        "IPO": ipo.METRICS,
        "Mutual funds": mf.METRICS,
        "Market": ["nifty", "nifty_change_pct", "nifty_30d_pct", "nifty_pe", "vix", "vix_change_pct", "nifty_adv_dec",
                   "fii_net_cr", "dii_net_cr"],
    }


def yf_symbol(symbol, exchange):
    return INDEX_YF.get(symbol) or f"{symbol}.{'BO' if exchange == 'BSE' else 'NS'}"


def daily_metrics(symbol, exchange, s):
    d = yf.Ticker(yf_symbol(symbol, exchange)).history(period="2y")
    if len(d) < 200 and exchange == "BSE":  # Yahoo's BSE daily history is often sparse; NSE history is the same stock
        d = yf.Ticker(yf_symbol(symbol, "NSE")).history(period="2y")
    c = d["Close"]
    last = c.iloc[-1]
    yr = d.tail(252)
    frame = indicators(d, s)
    ind = frame.iloc[-1].to_dict() | signals.daily(d, frame)
    if not d["Volume"].iloc[-1]:
        ind["vol_ratio"] = None  # indices have no volume
    # today's floor pivots come from the last completed session
    prev = d.iloc[-2] if d.index[-1].date() == datetime.now().date() else d.iloc[-1]
    ind |= {f"pivot_{k.lower()}": v for k, v in vatsal.pivots(prev["High"], prev["Low"], prev["Close"]).items()}
    ind |= vatsal.summary(d, s["vatsal"])
    ind["mtf_1d"] = tf_bias(d)
    return {
        "close": last,
        **ind,
        "high_52w": yr["High"].max(),
        "low_52w": yr["Low"].min(),
        "pct_from_52w_high": (last / yr["High"].max() - 1) * 100,
        "ret_1m": (last / c.iloc[-22] - 1) * 100,
        "ret_3m": (last / c.iloc[-64] - 1) * 100,
    }


def intraday_metrics(symbol, exchange, s):
    # ponytail: Yahoo 5m bars lag ~5 min. For tick-level data you need a paid broker feed (Kite/Groww ~Rs 500/mo).
    i = yf.Ticker(yf_symbol(symbol, exchange)).history(period="5d", interval="5m")
    t = i[i.index.date == i.index[-1].date()]
    tp = (t["High"] + t["Low"] + t["Close"]) / 3
    prev_close = i[i.index.date < i.index[-1].date()]["Close"].iloc[-1]
    price = t["Close"].iloc[-1]
    vol = t["Volume"]
    return {
        **vatsal.summary(i, s["vatsal"], prefix="vs5m"),
        "price": price,
        "price_time": str(t.index[-1]),
        "vwap": (tp * vol).sum() / vol.sum() if vol.sum() else None,  # indices have no volume
        "rsi_5m": rsi(i["Close"], s["rsi"]).iloc[-1],
        "vol_ratio_5m": vol.iloc[-1] / vol.mean() if vol.sum() else None,
        "day_change_pct": (price / prev_close - 1) * 100,
        "day_high": t["High"].max(),
        "day_low": t["Low"].min(),
        "orb_high": t["High"].head(s["orb_minutes"] // 5).max(),  # opening range
        "orb_low": t["Low"].head(s["orb_minutes"] // 5).min(),
    }


def fundamental_metrics(symbol, exchange):
    if symbol in INDEX_YF:
        return {}
    f = yf.Ticker(yf_symbol(symbol, exchange)).info
    pct = lambda k: f[k] * 100 if f.get(k) is not None else None
    return {
        "pe": f.get("trailingPE"),
        "pb": f.get("priceToBook"),
        "roe": pct("returnOnEquity"),
        "debt_to_equity": f.get("debtToEquity"),
        "revenue_growth": pct("revenueGrowth"),
        "earnings_growth": pct("earningsGrowth"),
        "profit_margin": pct("profitMargins"),
        "market_cap_cr": f["marketCap"] / 1e7 if f.get("marketCap") else None,
        "sector": f.get("sector"),
    }


def option_metrics(symbol):
    """Nearest-expiry option chain from NSE (F&O symbols only; BSE-only stocks have no options)."""
    # skip an expiry that is today: its IV/OI are meaningless by the afternoon
    today = datetime.now().date()
    expiry = next(e for e in nse(f"option-chain-contract-info?symbol={symbol}")["expiryDates"]
                  if datetime.strptime(e, "%d-%b-%Y").date() > today)
    kind = "Indices" if symbol in INDEX_YF else "Equity"
    rows = nse(f"option-chain-v3?type={kind}&symbol={symbol}&expiry={expiry}")["records"]["data"]
    leg = lambda o: o and {
        "ltp": o.get("lastPrice", 0), "bid": o.get("buyPrice1", 0), "ask": o.get("sellPrice1", 0),
        "iv": o.get("impliedVolatility", 0), "oi": o.get("openInterest", 0),
        "chg_oi": o.get("changeinOpenInterest", 0), "volume": o.get("totalTradedVolume", 0), "chg": o.get("change", 0),
    }
    raw = [{"strike": float(r["strikePrice"]), "CE": leg(r.get("CE")), "PE": leg(r.get("PE"))} for r in rows]
    chain = pd.DataFrame([{
        "strike": float(r["strikePrice"]),
        "ce_oi": r.get("CE", {}).get("openInterest", 0),
        "pe_oi": r.get("PE", {}).get("openInterest", 0),
        "ce_iv": r.get("CE", {}).get("impliedVolatility", 0),
        "pe_iv": r.get("PE", {}).get("impliedVolatility", 0),
        "spot": (r.get("CE") or r.get("PE"))["underlyingValue"],
    } for r in rows])
    spot = chain["spot"].iloc[0]
    if not spot or spot <= 0:  # NSE sometimes answers cloud servers / off-hours with a zeroed chain; strikes are unusable then
        raise ValueError("NSE returned the option chain without an underlying price; try again in a moment")
    k = chain["strike"]
    # max pain: strike where total option-writer payout is smallest
    pain = [(chain["ce_oi"] * (s - k).clip(lower=0) + chain["pe_oi"] * (k - s).clip(lower=0)).sum() for s in k]
    atm = chain.iloc[(k - spot).abs().argmin()]
    ivs = [x for x in (atm["ce_iv"], atm["pe_iv"]) if x]
    return {
        "spot": spot,
        "expiry": expiry,
        "days_to_expiry": (datetime.strptime(expiry, "%d-%b-%Y").date() - today).days,
        "pcr_oi": chain["pe_oi"].sum() / chain["ce_oi"].sum() if chain["ce_oi"].sum() else None,
        "max_pain": k.iloc[pd.Series(pain).argmin()],
        "atm_iv": sum(ivs) / len(ivs) if ivs else None,
        "call_wall": k.iloc[chain["ce_oi"].argmax()],  # highest call OI ~ resistance
        "put_wall": k.iloc[chain["pe_oi"].argmax()],  # highest put OI ~ support
        "_chain": raw,  # popped by collect(); not a metric
    }


TIMEFRAMES = {"15m": ("60d", "15m"), "1h": ("1y", "60m")}  # daily bias comes from daily_metrics' own candles


def tf_bias(d):
    """+1 / -1 / 0 for one timeframe: majority vote of price vs EMA 50, MACD vs signal, Supertrend direction."""
    c = d["Close"]
    macd = ema(c, 12) - ema(c, 26)
    tr = pd.concat([d["High"] - d["Low"], (d["High"] - c.shift()).abs(), (d["Low"] - c.shift()).abs()], axis=1).max(axis=1)
    _, st_dir = supertrend(d["High"], d["Low"], c, tr.ewm(alpha=1 / 10, adjust=False).mean(), 3)
    votes = int(np.sign(c.iloc[-1] - ema(c, 50).iloc[-1]) + np.sign(macd.iloc[-1] - ema(macd, 9).iloc[-1]) + st_dir.iloc[-1])
    return 1 if votes >= 2 else -1 if votes <= -2 else 0


def mtf_metrics(symbol, exchange):
    out = {}
    for tf, (period, iv) in TIMEFRAMES.items():
        d = yf.Ticker(yf_symbol(symbol, exchange)).history(period=period, interval=iv)
        if len(d) >= 60:
            out[f"mtf_{tf}"] = tf_bias(d)
    return out


def mtf_score(m):
    """Adds mtf_score (sum of the timeframe biases) and mtf_aligned (1 when every timeframe agrees and none is flat)."""
    b = [m[k] for k in ("mtf_15m", "mtf_1h", "mtf_1d") if m.get(k) is not None]
    if not b:
        return {}
    return {"mtf_score": sum(b), "mtf_aligned": int(len(set(b)) == 1 and b[0] != 0 and len(b) == 3)}


_EVENTS = {"at": 0.0, "rows": []}


def events_calendar():
    """Upcoming board meetings / results from NSE, cached for 30 minutes per process."""
    if time.time() - _EVENTS["at"] > 1800:
        rows = nse("event-calendar")
        _EVENTS.update(at=time.time(), rows=[{**r, "when": datetime.strptime(r["date"], "%d-%b-%Y").date()} for r in rows])
    return _EVENTS["rows"]


def event_metrics(symbol):
    """Days until this symbol's next corporate event (results, board meeting), for rules and the strike check."""
    today = datetime.now().date()
    mine = sorted((r for r in events_calendar() if r["symbol"] == symbol and r["when"] >= today), key=lambda r: r["when"])
    if not mine:
        return {"days_to_event": None, "event": None}
    return {"days_to_event": (mine[0]["when"] - today).days, "event": f"{mine[0]['purpose']} on {mine[0]['date']}"}


def market_metrics():
    idx = {x["index"]: x for x in nse("allIndices")["data"]}
    n, vix = idx["NIFTY 50"], idx["INDIA VIX"]
    flows = {x["category"]: float(x["netValue"]) for x in nse("fiidiiTradeReact")}
    adv, dec = int(n["advances"]), int(n["declines"])
    return {
        "nifty": n["last"],
        "nifty_change_pct": n["percentChange"],
        "nifty_30d_pct": n["perChange30d"],
        "nifty_pe": float(n["pe"]),
        "vix": vix["last"],
        "vix_change_pct": vix["percentChange"],
        "nifty_adv_dec": adv / dec if dec else None,
        "fii_net_cr": flows.get("FII/FPI"),
        "dii_net_cr": flows.get("DII"),
    }


# interval -> (yfinance period, yfinance interval, bars to show). Extra history warms up the EMAs.
CHART = {"5m": ("5d", "5m", 400), "15m": ("1mo", "15m", 400), "1D": ("2y", "1d", 250), "1W": ("10y", "1wk", 260)}
IST = 19800  # chart library draws UTC; shift so the axis reads IST


PIVOT_PERIOD = {"5m": "D", "15m": "D", "1D": "W-FRI", "1W": "ME"}  # pivots use the previous period of this size


def candles(symbol, exchange="NSE", interval="1D", vatsal_mode=False):
    period, iv, show = CHART[interval]
    d = yf.Ticker(yf_symbol(symbol, exchange)).history(period=period, interval=iv)
    if len(d) < 60 and exchange == "BSE":
        d = yf.Ticker(yf_symbol(symbol, "NSE")).history(period=period, interval=iv)
    s = load_settings()
    vcfg = s["vatsal"]
    ind = indicators(d, s)[[f"ema_{n}" for n in (vcfg["emas"] if vatsal_mode else s["ema"])]]
    if interval.endswith("m") and d["Volume"].sum():
        # session VWAP, reset every day
        day = d.index.date
        pv = ((d["High"] + d["Low"] + d["Close"]) / 3 * d["Volume"]).groupby(day).cumsum()
        ind["vwap"] = pv / d["Volume"].groupby(day).cumsum()

    # Vatsal overlays are computed on the full history, then clipped to the visible bars
    times = [int(ts.timestamp()) + IST for ts in d.index]
    first = len(d) - min(show, len(d))
    at = lambda i: times[max(i, first)]
    sig = vatsal.signals(d, vcfg)["signal"].to_numpy()
    markers = [{"time": times[i], "dir": int(sig[i])} for i in range(first, len(d)) if sig[i]]
    zones = [{"t1": at(z["start"]), "kind": z["kind"], "top": round(float(z["top"]), 2), "bottom": round(float(z["bottom"]), 2)}
             for z in vatsal.supply_demand(d, vcfg) + vatsal.liquidity_zones(d, vcfg)[-10:]
             + vatsal.fair_value_gaps(d, vcfg)[-vcfg["fvg_show"]:]]
    f = vatsal.fib(d, vcfg)
    fibo = f and {"t1": at(f["start"]), "t2": at(f["end"]),
                  "levels": {str(k): round(float(v), 2) for k, v in f["levels"].items()}}
    grp = d.groupby(d.index.tz_localize(None).to_period(PIVOT_PERIOD[interval][0] if interval != "1W" else "M"))
    hlc = grp.agg({"High": "max", "Low": "min", "Close": "last"})
    piv = {k: round(float(v), 2) for k, v in vatsal.pivots(*hlc.iloc[-2][["High", "Low", "Close"]]).items()} if len(hlc) > 1 else None

    d, ind = d.tail(show), ind.tail(show)
    r = lambda col: [None if x != x else round(float(x), 2) for x in col]
    return {
        "time": times[first:],
        "open": r(d["Open"]), "high": r(d["High"]), "low": r(d["Low"]), "close": r(d["Close"]),
        "volume": [int(v) for v in d["Volume"]],
        "lines": {k: r(ind[k]) for k in ind.columns},
        "vatsal": {"markers": markers, "zones": zones, "fib": fibo, "pivots": piv} if vatsal_mode else {},
    }


def collect(symbol, exchange="NSE"):
    """Every source is independent: one failing (e.g. no options for this stock) leaves the others."""
    out, errors = {"symbol": symbol, "exchange": exchange}, {}
    s = load_settings()
    sources = [("daily", lambda: daily_metrics(symbol, exchange, s)),
               ("intraday", lambda: intraday_metrics(symbol, exchange, s)),
               ("fundamentals", lambda: fundamental_metrics(symbol, exchange)),
               ("options", lambda: option_metrics(symbol)),
               ("timeframes", lambda: mtf_metrics(symbol, exchange)),
               ("events", lambda: event_metrics(symbol)),
               ("market", market_metrics)]
    with ThreadPoolExecutor(len(sources)) as pool:  # all network-bound: total time = the slowest source, not the sum
        futures = [(name, pool.submit(fn)) for name, fn in sources]
    for name, f in futures:  # merged in the listed order, as before
        try:
            out.update(f.result())
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"
    chain = out.pop("_chain", None)
    out |= signals.intraday(out)
    out |= signals.score(out)
    out |= mtf_score(out)
    num = lambda v: None if v != v else round(float(v), 2)  # NaN -> None (NaN also breaks JSON)
    out = {k: (num(v) if isinstance(v, numbers.Real) and not isinstance(v, bool) else v) for k, v in out.items()}  # incl. numpy ints
    return out, errors, chain


if __name__ == "__main__":
    import sys
    m, e, _ = collect(sys.argv[1] if len(sys.argv) > 1 else "RELIANCE", sys.argv[2] if len(sys.argv) > 2 else "NSE")
    print(json.dumps(m, indent=2, default=str), "\nerrors:", e)
