"""Learn tab: beginner lessons, and classic strategies (RSI, VWAP, Fibonacci ...) you can backtest on any stock or index.

A strategy turns candles into BUY / SELL / HOLD labels at each close; backtest.simulate fills them at the next open.
Options mode re-prices each trade as an ATM option bought at entry, using Black-Scholes with the recent realised
volatility as IV. shortcut: free data has no option price history, so option results are a model estimate, not real fills.
"""
import math

import numpy as np
import pandas as pd
import yfinance as yf

import backtest
import data
from setups import bs_price

LESSONS = [
    ("1 · What trading is (and isn't)", """
**Investing** = buying a business and holding it for years. **Trading** = buying and selling over minutes to weeks to profit
from price moves. Traders win by having a small edge and repeating it many times with controlled losses, not by being right
every time. Most beginners lose money, usually because of no plan, big position sizes and no stop-loss.

- **Long (BUY first)**: you profit if price rises. **Short (SELL first)**: you profit if price falls (intraday or via F&O in India).
- **Intraday (MIS)**: closed the same day, broker gives leverage. **Delivery (CNC)**: shares go to your demat, hold as long as you like.
- **Swing**: hold a few days to weeks. **Positional**: weeks to months.
"""),
    ("2 · Order types", """
| Order | What it does | Use it when |
|---|---|---|
| **Market** | Fills immediately at the best available price | You need to get in/out now |
| **Limit** | Fills only at your price or better | You want a specific entry |
| **Stop-loss (SL)** | Becomes a limit order once the *trigger* price is touched | Exiting a losing trade at a planned level |
| **SL-M** | Becomes a market order once triggered | Guaranteed exit, price may slip |
| **GTT / OCO** | Stop and target placed together; one cancels the other | Swing trades you can't watch all day |

In the **Paper Trading** tab, orders are market orders, and your stop/target behave like resting SL and limit orders.
"""),
    ("3 · Stop-loss (SL)", """
A **stop-loss** is the price where you admit the trade idea is wrong and exit. Decide it **before** you enter.

- Put it where the setup is invalid, not at a random %: below the recent swing low / support for a long, above resistance for a short.
- Or use volatility: **entry − 1.5 × ATR** (ATR = average daily range). Wider for volatile stocks, tighter for calm ones.
- **Never move a stop further away** to "give it room". Moving it closer (trailing) to lock in profit is fine.
- **Trailing stop**: as price moves your way, raise the stop (e.g. under each new higher low, or under the 20 EMA).

*Example*: buy RELIANCE at ₹1,300, recent swing low ₹1,270 → stop ₹1,265. Risk per share = ₹35.
"""),
    ("4 · Target (TGT) and risk-reward", """
A **target** is where you plan to take profit: the next resistance, a prior high, or a multiple of your risk.

**Risk-reward (R:R)** = (target − entry) ÷ (entry − stop). With entry ₹1,300, stop ₹1,265, target ₹1,370: reward 70 ÷ risk 35 = **1:2**.

Why it matters: at 1:2 you can be wrong **6 times out of 10** and still make money.

| Win rate | R:R needed to break even |
|---|---|
| 30% | 1 : 2.3 |
| 40% | 1 : 1.5 |
| 50% | 1 : 1 |

Many traders book half at 1R or 2R and trail the stop on the rest. Skip trades below **1:1.5**.
"""),
    ("5 · Position sizing (the 1% rule)", """
Size each trade so that hitting the stop loses a fixed small part of your capital, usually **0.5–2%**.

**Quantity = (capital × risk %) ÷ (entry − stop)**

Capital ₹5,00,000, risk 1% = ₹5,000. Entry ₹1,300, stop ₹1,265 → risk/share ₹35 → **quantity 142 shares** (₹1.85 L invested).
Ten losses in a row then cost about 10%, not your whole account. Use the calculator below.
"""),
    ("6 · Trend, support & resistance", """
- **Uptrend**: higher highs and higher lows. **Downtrend**: lower highs and lower lows. Trade *with* the trend; buy dips in uptrends.
- **Support**: a price where buyers stepped in before (a floor). **Resistance**: where sellers stepped in (a ceiling).
- When resistance breaks it often becomes support (and vice versa). Round numbers and 52-week highs/lows act as levels too.
- **EMA 200**: price above it = long-term uptrend; below = downtrend. **EMA 20/50**: shorter trend and pullback zones.
"""),
    ("7 · Candlesticks & volume", """
Each candle shows **Open, High, Low, Close** for a period. Green = closed above open, red = below.

- **Long lower wick (hammer)** at support: buyers rejected lower prices. **Long upper wick (shooting star)** at resistance: sellers rejected.
- **Engulfing**: a candle whose body covers the previous one, often a reversal sign.
- **Volume** confirms: a breakout on 1.5–2× average volume is more trustworthy than one on thin volume.
"""),
    ("8 · Options basics (CE / PE)", """
- **Call (CE)**: right to buy at the **strike**. Gains when price rises. **Put (PE)**: right to sell at the strike. Gains when price falls.
- **Premium**: the price of the option. A buyer's max loss is the premium; a seller's (writer's) loss can be unlimited.
- **Lot size**: options trade in lots set by NSE (NIFTY is 65 as of 2026; the app looks up the current size). P&L = premium change × lot size × lots.
- **Expiry**: weekly (indices) or monthly. Value **decays** every day (**theta**), fastest in the last week.
- **ITM / ATM / OTM**: in-, at- or out-of-the-money. OTM is cheap but needs a big move; ATM is the usual balance.
- **Delta**: how much the premium moves per ₹1 of the stock (~0.5 for ATM). **IV**: implied volatility; high IV = expensive options.
- Beginner rule: **buy options with a stop on the premium** (e.g. −30%), avoid selling naked options until you understand margin.
"""),
    ("9 · Costs, psychology & a journal", """
- **Charges**: brokerage, STT, exchange fees, GST, stamp duty, plus slippage. Roughly 0.05–0.15% per side for stocks; they add up for scalpers.
- **Psychology**: FOMO (chasing after a big move), revenge trading after a loss, and averaging down a loser are the classic account-killers.
- **Daily loss limit**: stop trading for the day after losing e.g. 3R.
- **Journal** every trade (the Journal tab): why you entered, stop, target, result, and what you'd do differently. Review weekly.
"""),
    ("10 · Your first paper trade", """
1. Go to **Paper Trading**. You start with ₹10 lakh of dummy money; add as much more as you like.
2. Pick a liquid stock (RELIANCE, TCS, HDFCBANK) or an option like `NIFTY 25000 CE`.
3. Check the chart on **Analyze**: trend, nearest support (stop) and resistance (target).
4. Size it with the 1% rule, enter **stop** and **target**, place the order.
5. Click **Refresh prices**: stops and targets close automatically when crossed.
6. After 20–30 paper trades, look at your win rate and average R. Only then think about real money.
"""),
]


def _cross_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


def vwap(d, intraday):
    """Session VWAP intraday; a rolling 20-bar VWAP on daily bars. Indices have no volume, so bars weigh equally there."""
    tp = (d["High"] + d["Low"] + d["Close"]) / 3
    v = d["Volume"] if d["Volume"].sum() else pd.Series(1.0, index=d.index)
    if intraday:
        day = d.index.date
        return (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum()
    return (tp * v).rolling(20).sum() / v.rolling(20).sum()


def _labels(buy, sell):
    return pd.Series(np.where(buy, "BUY", np.where(sell, "SELL", "HOLD")), index=buy.index)


def rsi_reversal(d, ind, intraday):
    r = ind["rsi"]
    return _labels(_cross_up(r, pd.Series(30.0, index=r.index)), _cross_up(pd.Series(70.0, index=r.index), r))


def vwap_cross(d, ind, intraday):
    vw = vwap(d, intraday)
    return _labels(_cross_up(d["Close"], vw), _cross_up(vw, d["Close"]))


def fib_pullback(d, ind, intraday, n=50):
    """Uptrend pullback into the 50–61.8% retracement of the last n-bar swing, closing back above 61.8%."""
    hi, lo = d["High"].rolling(n).max().shift(), d["Low"].rolling(n).min().shift()
    f618, f786 = hi - 0.618 * (hi - lo), hi - 0.786 * (hi - lo)
    c, e200 = d["Close"], ind["ema_200"] if "ema_200" in ind else data.ema(d["Close"], 200)
    buy = (d["Low"] <= hi - 0.5 * (hi - lo)) & (c > f618) & (c > e200)
    return _labels(buy, (c < f786) | (d["High"] >= hi))


def ema_cross(d, ind, intraday):
    f, s = data.ema(d["Close"], 9), data.ema(d["Close"], 21)
    return _labels(_cross_up(f, s), _cross_up(s, f))


def macd_cross(d, ind, intraday):
    return _labels(_cross_up(ind["macd"], ind["macd_signal"]), _cross_up(ind["macd_signal"], ind["macd"]))


def bollinger_revert(d, ind, intraday):
    c = d["Close"]
    return _labels(c < ind["bb_lower"], c > ind["bb_mid"])


def supertrend_flip(d, ind, intraday):
    st_ = ind["supertrend_dir"]
    return _labels((st_ == 1) & (st_.shift() == -1), (st_ == -1) & (st_.shift() == 1))


def breakout(d, ind, intraday):
    c = d["Close"]
    return _labels(c > d["High"].rolling(20).max().shift(), c < d["Low"].rolling(10).min().shift())


STRATEGIES = {  # name: (function, beginner explanation)
    "RSI reversal": (rsi_reversal, """**RSI** (Relative Strength Index, 0–100) measures how strong recent up-moves are versus down-moves.
Below **30** = oversold (fell too fast), above **70** = overbought. **Buy** when RSI climbs back above 30, **sell** when it drops back
below 70. Works best in sideways markets; in strong trends RSI can stay overbought for weeks."""),
    "VWAP cross": (vwap_cross, """**VWAP** (Volume-Weighted Average Price) is the average price paid today, weighted by volume; institutions use it as
the "fair" price. Price above VWAP = buyers in control. **Buy** when price closes above VWAP, **sell** when it closes below.
Pick a **5m/15m** interval for the real intraday VWAP (resets each session); on daily bars a 20-day rolling VWAP is used."""),
    "Fibonacci pullback": (fib_pullback, """**Fibonacci retracements** (23.6%, 38.2%, 50%, 61.8%, 78.6%) mark how far a move pulls back before resuming.
Here: in an uptrend (above EMA 200), **buy** when price dips into the **50–61.8%** zone of the last 50-bar swing and closes back above 61.8%.
**Exit** if it breaks below **78.6%** (setup failed) or retests the swing high (target)."""),
    "EMA 9/21 crossover": (ema_cross, """An **EMA** (exponential moving average) follows price, weighting recent bars more. When the fast **EMA 9** crosses
above the slow **EMA 21** momentum has turned up: **buy**. Cross below: **sell**. Simple trend following; it whipsaws in ranges."""),
    "MACD crossover": (macd_cross, """**MACD** = EMA 12 − EMA 26 (momentum); its **signal line** is a 9-EMA of MACD. **Buy** when MACD crosses above
the signal, **sell** when it crosses below. Uses your periods from the Indicators tab."""),
    "Bollinger mean reversion": (bollinger_revert, """**Bollinger Bands** are a 20-period average ± 2 standard deviations; price spends ~95% of the
time inside. **Buy** when price closes below the lower band (stretched down), **sell** when it gets back to the middle band."""),
    "Supertrend flip": (supertrend_flip, """**Supertrend** is an ATR-based trailing line: below price in an uptrend, above it in a downtrend. **Buy** when it
flips up, **sell** when it flips down. A clean trend-follower with built-in trailing stop."""),
    "20-bar breakout": (breakout, """A **breakout** (Donchian/turtle style): **buy** when price closes above the highest high of the last 20 bars,
**exit** when it closes below the lowest low of the last 10. Catches big trends, loses small on false breakouts."""),
}

INTERVALS = {  # label: (yfinance interval, max period it allows, bars per year for annualising volatility)
    "1d": ("1d", None, 252), "1h": ("60m", "730d", 252 * 7), "15m": ("15m", "60d", 252 * 25), "5m": ("5m", "60d", 252 * 75),
}


def history(symbol, exchange, period, interval):
    iv, cap, _ = INTERVALS[interval]
    return yf.Ticker(data.yf_symbol(symbol, exchange)).history(period=cap or period, interval=iv)


def option_trades(trades, d, bars_year, expiry_days=30, lot=1, cost=20.0):
    """Re-price each underlying trade as buying an ATM option: CE for a long, PE for a short.
    IV = 20-bar realised volatility at entry, kept for the exit. cost = ₹ per side per lot (brokerage + charges)."""
    rv = np.log(d["Close"]).diff().rolling(20).std() * math.sqrt(bars_year) * 100
    rows = []
    for _, t in trades.iterrows():
        kind = "CE" if t["side"] == "LONG" else "PE"
        v = rv.asof(pd.Timestamp(t["entry_date"]).tz_localize(d.index.tz))
        iv = float(v) if v == v and v > 0 else 20.0  # NaN (too early for 20 bars) -> a typical 20%
        held = (pd.Timestamp(t["exit_date"]) - pd.Timestamp(t["entry_date"])).total_seconds() / 86400  # fractional: intraday decays too
        t0, t1 = expiry_days / 365, max(expiry_days - held, 0) / 365
        p0, p1 = bs_price(t["entry"], t["entry"], t0, iv, kind), bs_price(t["exit"], t["entry"], t1, iv, kind)
        pl = (p1 - p0) * lot - 2 * cost
        rows.append({"option": f"ATM {kind} @ {t['entry']:,.0f}", "entry_date": t["entry_date"], "exit_date": t["exit_date"],
                     "iv_pct": round(iv, 1), "premium_in": round(p0, 2), "premium_out": round(p1, 2),
                     "ret_pct": round((p1 / p0 - 1) * 100, 2) if p0 else 0.0, "pnl_rs": round(pl, 0), "exit_why": t["exit_why"]})
    return pd.DataFrame(rows)


def run(symbol, strategy, exchange="NSE", period="3y", interval="1d", **sim):
    """History -> strategy labels -> backtest.simulate. Trading starts after backtest.WARMUP bars of indicator warm-up."""
    d = history(symbol, exchange, period, interval)
    if len(d) <= backtest.WARMUP + 20:
        raise ValueError(f"only {len(d)} candles for {symbol}; need more than {backtest.WARMUP + 20}. Pick a longer history.")
    ind = data.indicators(d, data.load_settings())
    labels = STRATEGIES[strategy][0](d, ind, interval != "1d")
    w = d.iloc[backtest.WARMUP:]
    trades, equity = backtest.simulate(w, labels, ind["atr"].iloc[backtest.WARMUP:], **sim)
    return {"d": w, "trades": trades, "equity": equity, "stats": backtest.stats(trades, equity, w),
            "bars_year": INTERVALS[interval][2]}


if __name__ == "__main__":  # offline self-checks on synthetic candles
    idx = pd.bdate_range("2024-01-01", periods=300)
    px = pd.Series(100 + 10 * np.sin(np.arange(300) / 8), index=idx)
    d = pd.DataFrame({"Open": px, "High": px + 1, "Low": px - 1, "Close": px, "Volume": 1000.0})
    ind = data.indicators(d, data.DEFAULTS)
    for name, (fn, _) in STRATEGIES.items():
        lab = fn(d, ind, False)
        assert len(lab) == len(d) and set(lab) <= {"BUY", "SELL", "HOLD"}, name
    assert (rsi_reversal(d, ind, False) == "BUY").any() and (ema_cross(d, ind, False) == "SELL").any()
    i5 = pd.date_range("2024-01-01 09:15", periods=6, freq="5min").append(pd.date_range("2024-01-02 09:15", periods=2, freq="5min"))
    di = pd.DataFrame({"High": [10, 12, 11, 13, 12, 14, 20, 22], "Low": [8, 10, 9, 11, 10, 12, 18, 20], "Volume": 1.0}, index=i5)
    di["Close"] = (di["High"] + di["Low"]) / 2
    vw = vwap(di, True)
    assert vw.iloc[0] == 9 and vw.iloc[6] == 19  # resets at the new session
    tr = pd.DataFrame([{"side": "LONG", "entry_date": idx[100].date(), "entry": 100.0, "exit_date": idx[110].date(), "exit": 110.0, "exit_why": "x"}])
    ot = option_trades(tr, d, 252, lot=10, cost=0)
    assert ot.iloc[0]["premium_out"] > ot.iloc[0]["premium_in"] and ot.iloc[0]["pnl_rs"] > 0  # call gains on a 10% rise
    print("ok")
