"""Paper trading: a pretend account in paper.json. Dummy money only; nothing here reaches a broker.

Market orders fill at the latest Yahoo price (stocks) or NSE option-chain LTP (options, nearest expiry).
Commodities (GOLD, CRUDEOIL ...) and forex pairs (EURUSD, USDINR ...) trade at Yahoo's quote in its own currency;
`fx` turns it into rupees at the rate on the day you open (USD for commodities, the quote currency for a pair).
Cash accounting: opening blocks qty × entry × fx (buys and shorts alike); closing returns that plus the P&L.
shortcut: shorts and option writing block only qty × price, not real SPAN margin; fine for practice, not for margin planning.
"""
import json
from datetime import date, datetime
from pathlib import Path

import yfinance as yf

import data
import setups

FILE = Path(__file__).with_name("paper.json")
START = 1_000_000.0  # ₹10 lakh of play money to begin with


def new():
    return {"cash": START, "deposited": START, "positions": [], "closed": [], "next_id": 1}


def load():
    try:
        return json.loads(FILE.read_text())
    except (FileNotFoundError, ValueError):
        return new()


def save(acct):
    FILE.write_text(json.dumps(acct, indent=1, default=str))


def add_funds(acct, amount):
    if amount <= 0:
        raise ValueError("amount must be positive")
    acct["cash"] += amount
    acct["deposited"] += amount


def stock_price(symbol, exchange="NSE"):
    t = yf.Ticker(data.yf_symbol(symbol, exchange))
    px = t.fast_info.get("last_price")
    if not px:
        px = t.history(period="5d")["Close"].iloc[-1]
    return float(px)


def currency(symbol):
    """Currency the symbol is quoted in: USD for global commodity futures, the last three letters of a forex pair, else INR."""
    if symbol in data.COMMODITY_YF:
        return "USD"
    return symbol[3:] if symbol in data.FOREX_YF else "INR"


def to_inr(ccy):
    """Rupees per 1 unit of ccy."""
    return 1.0 if ccy == "INR" else float(yf.Ticker(f"{ccy}INR=X").history(period="5d")["Close"].iloc[-1])


def option_quote(symbol, strike, kind):
    """(ltp, expiry, matched strike) from the nearest-expiry NSE chain."""
    o = data.option_metrics(symbol)
    row = min(o["_chain"], key=lambda r: abs(r["strike"] - strike))
    if abs(row["strike"] - strike) > 1e-6:
        raise ValueError(f"no {strike:g} strike in the {o['expiry']} chain; nearest is {row['strike']:g}")
    q = row.get(kind)
    if not q or not q.get("ltp"):
        raise ValueError(f"{symbol} {strike:g} {kind} has no traded price right now")
    return float(q["ltp"]), o["expiry"], row["strike"]


def quote(pos):
    """Current price of a position. An expired option settles at intrinsic value off the underlying."""
    if not pos.get("kind"):
        return stock_price(pos["symbol"], pos.get("exchange", "NSE"))
    if datetime.strptime(pos["expiry"], "%d-%b-%Y").date() < date.today():
        return setups.bs_price(stock_price(pos["symbol"]), pos["strike"], 0, 0, pos["kind"])
    return option_quote(pos["symbol"], pos["strike"], pos["kind"])[0]


def pnl(pos, px):
    return (px - pos["entry"]) * pos["qty"] * (1 if pos["side"] == "BUY" else -1) * pos.get("fx", 1.0)


def blocked(pos):
    return pos["qty"] * pos["entry"] * pos.get("fx", 1.0)


def open_position(acct, symbol, side, qty, price, exchange="NSE", kind=None, strike=None, expiry=None, stop=None, target=None, fx=1.0):
    if qty <= 0 or price <= 0:
        raise ValueError("quantity and price must be positive")
    cost = qty * price * fx
    if cost > acct["cash"]:
        raise ValueError(f"needs ₹{cost:,.0f} but cash is ₹{acct['cash']:,.0f}. Add more dummy money first.")
    sgn = 1 if side == "BUY" else -1
    for lv, name, bad in ((stop, "stop", lambda x: (x - price) * sgn >= 0), (target, "target", lambda x: (x - price) * sgn <= 0)):
        if lv and bad(lv):
            raise ValueError(f"a {side} {name} must be {'below' if (name == 'stop') == (side == 'BUY') else 'above'} the entry {price:,.2f}")
    ccy = currency(symbol)
    inst = f"{symbol} {strike:g} {kind} {expiry}" if kind else symbol if ccy == "INR" else f"{symbol} (in {ccy}, ₹{fx:,.2f}/{ccy})"
    pos = {"id": acct["next_id"], "symbol": symbol, "exchange": exchange, "instrument": inst, "kind": kind, "strike": strike,
           "expiry": expiry, "side": side, "qty": qty, "entry": price, "stop": stop or None, "target": target or None,
           "opened": datetime.now().strftime("%Y-%m-%d %H:%M"), "fx": fx}
    acct["next_id"] += 1
    acct["cash"] -= cost
    acct["positions"].append(pos)
    return pos


def close_position(acct, pos_id, price, why="manual"):
    pos = next(p for p in acct["positions"] if p["id"] == pos_id)
    acct["positions"].remove(pos)
    p = pnl(pos, price)
    acct["cash"] += blocked(pos) + p
    acct["closed"].append(pos | {"exit": price, "closed": datetime.now().strftime("%Y-%m-%d %H:%M"), "pnl": round(p, 2), "why": why})
    return p


def hit(pos, px):
    """'stop' / 'target' when the latest price has crossed one, else None."""
    up = pos["side"] == "BUY"
    if pos.get("stop") and (px <= pos["stop"] if up else px >= pos["stop"]):
        return "stop"
    if pos.get("target") and (px >= pos["target"] if up else px <= pos["target"]):
        return "target"
    return None


def check_exits(acct, prices):
    """Close every position whose stop/target was crossed (at that level, as a resting order would). prices: {id: ltp}."""
    done = []
    for pos in list(acct["positions"]):
        px = prices.get(pos["id"])
        if px is None:
            continue
        expired = pos.get("kind") and datetime.strptime(pos["expiry"], "%d-%b-%Y").date() < date.today()
        why = "expired" if expired else hit(pos, px)
        if why:
            fill = px if why == "expired" else pos[why]
            done.append((pos["instrument"], why, close_position(acct, pos["id"], fill, why)))
    return done


if __name__ == "__main__":
    a = new()
    add_funds(a, 5_000_000)
    assert a["cash"] == 6_000_000
    p = open_position(a, "TEST", "BUY", 100, 50.0, stop=45, target=60)
    assert a["cash"] == 6_000_000 - 5000
    assert check_exits(a, {p["id"]: 52}) == [] and check_exits(a, {p["id"]: 61})[0][1] == "target"
    assert a["cash"] == 6_000_000 + 1000 and a["closed"][0]["pnl"] == 1000  # filled at the 60 target, not 61
    s = open_position(a, "TEST", "SELL", 10, 100.0, stop=110)
    assert check_exits(a, {s["id"]: 112})[0][2] == -100  # short stopped at 110
    g = open_position(a, "GOLD", "BUY", 2, 2000.0, fx=85.0)  # 2 oz at $2000, $1 = ₹85
    assert currency("GOLD") == "USD" and currency("EURUSD") == "USD" and currency("USDJPY") == "JPY" and currency("TCS") == "INR"
    cash = a["cash"]
    assert close_position(a, g["id"], 2010.0) == 2 * 10 * 85 and a["cash"] == cash + 2 * 2000 * 85 + 1700
    for bad in (lambda: open_position(a, "X", "BUY", 1, 100.0, stop=105), lambda: open_position(a, "X", "BUY", 10**9, 100.0)):
        try:
            bad()
            raise AssertionError("should have raised")
        except ValueError:
            pass
    print("ok")
