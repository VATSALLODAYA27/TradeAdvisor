"""News and analyst views. Pure data, no verdicts (those come from the [news] section of rules.toml).

Market headlines: Economic Times markets RSS. Stock headlines: Google News RSS (last 30 days).
Analyst consensus: Yahoo (mean rating 1 = strong buy … 5 = sell, analyst count, mean/high/low target).
Each headline is read by Groq: sentiment for the share price (-1 … +1) and, when the headline reports one,
the brokerage call (broker, BUY/SELL/HOLD, target). Without GROQ_API_KEY the headlines still show, unscored.
"""
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests
import yfinance as yf

import data

ET_MARKETS = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
GOOGLE = "https://news.google.com/rss/search?q={}&hl=en-IN&gl=IN&ceid=IN:en"
WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
METRICS = ["news_count", "news_sentiment", "news_positive", "news_negative", "broker_buy_calls", "broker_sell_calls",
           "broker_target_avg", "analyst_rating", "analyst_count", "analyst_buy_pct", "target_mean", "target_high",
           "target_low", "target_upside_pct"]
READER = (
    "You read Indian stock-market news headlines. Return JSON {\"items\": [...]} with one object per numbered headline, "
    "in order: {\"i\": number, \"s\": number from -1 to 1, \"call\": \"BUY\"|\"SELL\"|\"HOLD\"|null, \"broker\": string|null, "
    "\"target\": number|null}. s = how good the news is for the share price of the company it is about (-1 very bad, "
    "0 neutral or unclear, 1 very good); for market-wide headlines, for the Indian market. Fill call/broker/target only "
    "when the headline itself reports an analyst or brokerage recommendation (Accumulate/Add/Overweight = BUY, "
    "Reduce/Underweight = SELL, Neutral = HOLD); target is the rupee price target as a plain number. Never guess."
)


def rss(url, n=30, days=None):
    """RSS items newest first: title, source, link, published (UTC). `days` drops older items."""
    root = ET.fromstring(requests.get(url, headers=WEB, timeout=20).content)
    cut = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    out, seen = [], set()
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        title, src = (it.findtext("title") or "").strip(), it.findtext("source")
        if " - " in title and (not src or title.endswith(f" - {src}")):  # Google News appends " - Outlet" to titles
            title, src = title.rsplit(" - ", 1)
        key = "".join(ch for ch in title.lower() if ch.isalnum())[:45]  # same story from several outlets counts once
        if title and key not in seen and (cut is None or when >= cut):
            seen.add(key)
            out.append({"title": title, "source": src or "Economic Times", "link": it.findtext("link"), "published": when})
    return sorted(out, key=lambda x: x["published"], reverse=True)[:n]


def read(items, about=None):
    """Groq reads every headline in one request; adds s / call / broker / target to each item. Returns an error or None.
    `about` names the company to score for (a headline about a supplier's loan isn't news for the lender's shares)."""
    key = os.environ.get("GROQ_API_KEY")
    if not items:
        return None
    if not key:
        return "GROQ_API_KEY is not set, so headlines are unscored"
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=60, json={
        "model": "openai/gpt-oss-120b", "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": READER},
                     {"role": "user", "content": (f"Score s for the share price of {about} only.\n" if about else "")
                      + "\n".join(f"{i}. {x['title']}" for i, x in enumerate(items))}]})
    if not r.ok:  # rate limit / bad key shouldn't hide the headlines
        return f"Groq HTTP {r.status_code}"
    try:
        got = {int(o["i"]): o for o in json.loads(r.json()["choices"][0]["message"]["content"])["items"]}
    except (KeyError, ValueError, TypeError):
        return "Groq returned an unreadable answer"
    for i, x in enumerate(items):
        o = got.get(i, {})
        s = o.get("s")
        x["s"] = max(-1.0, min(1.0, float(s))) if isinstance(s, (int, float)) else None
        x["call"] = o.get("call") if o.get("call") in ("BUY", "SELL", "HOLD") else None
        x["broker"] = o.get("broker") if x["call"] else None
        x["target"] = o.get("target") if x["call"] and isinstance(o.get("target"), (int, float)) and o["target"] > 0 else None
    return None


def analyst(symbol, exchange="NSE"):
    """Yahoo's analyst consensus and this month's rating counts."""
    t = yf.Ticker(data.yf_symbol(symbol, exchange))
    info = t.info
    out = {k: info.get(k) for k in ("targetMeanPrice", "targetHighPrice", "targetLowPrice", "recommendationMean",
                                     "recommendationKey", "numberOfAnalystOpinions", "currentPrice", "longName")}
    try:
        rs = t.recommendations_summary
        now = rs[rs["period"] == "0m"].iloc[0]
        out["counts"] = {k: int(now[k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    except Exception:
        out["counts"] = None
    return out


def metrics(price, items, a):
    """Flat metrics for the rules. Missing data stays None, which makes rules using it fail."""
    m = {k: None for k in METRICS}
    scored = [x["s"] for x in items if x.get("s") is not None]
    m["news_count"] = len(items)
    if scored:
        m |= {"news_sentiment": round(sum(scored) / len(scored), 2), "news_positive": sum(s >= 0.25 for s in scored),
              "news_negative": sum(s <= -0.25 for s in scored)}
    calls = [x for x in items if x.get("call")]
    targets = [x["target"] for x in calls if x.get("target")]
    m |= {"broker_buy_calls": sum(x["call"] == "BUY" for x in calls), "broker_sell_calls": sum(x["call"] == "SELL" for x in calls),
          "broker_target_avg": round(sum(targets) / len(targets), 2) if targets else None}
    if a:
        c = a.get("counts") or {}
        total = sum(c.values()) if c else 0
        m |= {"analyst_rating": a.get("recommendationMean"), "analyst_count": a.get("numberOfAnalystOpinions"),
              "analyst_buy_pct": round((c["strongBuy"] + c["buy"]) / total * 100, 1) if total else None,
              "target_mean": a.get("targetMeanPrice"), "target_high": a.get("targetHighPrice"), "target_low": a.get("targetLowPrice")}
        if price and a.get("targetMeanPrice"):
            m["target_upside_pct"] = round((a["targetMeanPrice"] / price - 1) * 100, 2)
    return m


def stock(symbol, exchange="NSE", days=30):
    """Headlines (scored), analyst consensus and metrics for one stock. Each source fails on its own."""
    errors, a, items = {}, None, []
    try:
        a = analyst(symbol, exchange)
    except Exception as ex:
        errors["analysts"] = f"{type(ex).__name__}: {ex}"
    name = (a or {}).get("longName") or symbol
    try:
        items = rss(GOOGLE.format(quote_plus(f'"{symbol}" OR "{name}" share')), n=25, days=days)
        # brokerage calls rarely make the general feed; ask for them directly and add the ones not already there
        calls = rss(GOOGLE.format(quote_plus(f'"{symbol}" OR "{name}" target price brokerage')), n=10, days=days * 3)
        have = {x["title"].lower()[:45] for x in items}
        items += [x for x in calls if x["title"].lower()[:45] not in have]
    except Exception as ex:
        errors["news"] = f"{type(ex).__name__}: {ex}"
    if err := read(items, f"{name} ({symbol})"):
        errors["sentiment"] = err
    price = (a or {}).get("currentPrice")
    return {"symbol": symbol, "name": name, "price": price, "analyst": a, "headlines": items,
            "metrics": metrics(price, items, a), "errors": errors}


def market(n=25):
    items = rss(ET_MARKETS, n=n)
    return items, read(items)


if __name__ == "__main__":  # offline self-check
    xml = b"""<rss><channel>
      <item><title>Buy HDFC Bank; target Rs 1,850: ICICI Securities - Moneycontrol</title><link>u1</link>
            <pubDate>Thu, 15 Oct 2026 07:00:00 GMT</pubDate></item>
      <item><title>Old story</title><link>u2</link><pubDate>Mon, 01 Jan 2024 07:00:00 GMT</pubDate></item>
    </channel></rss>"""
    real = requests.get
    requests.get = lambda *a, **k: type("R", (), {"content": xml})()
    got = rss("x", days=36500)
    assert got[0]["title"] == "Buy HDFC Bank; target Rs 1,850: ICICI Securities" and got[0]["source"] == "Moneycontrol" and len(got) == 2
    assert len(rss("x", days=7, n=5)) <= 1  # the 2024 item is dropped
    requests.get = real
    items = [{"s": 0.8, "call": "BUY", "target": 1850.0}, {"s": -0.5, "call": None, "target": None}, {"s": None, "call": None}]
    a = {"recommendationMean": 1.5, "numberOfAnalystOpinions": 10, "targetMeanPrice": 1650.0, "targetHighPrice": 1900.0,
         "targetLowPrice": 1300.0, "counts": {"strongBuy": 3, "buy": 5, "hold": 1, "sell": 1, "strongSell": 0}}
    m = metrics(1500.0, items, a)
    assert m["news_sentiment"] == 0.15 and m["news_positive"] == 1 and m["news_negative"] == 1 and m["news_count"] == 3
    assert m["broker_buy_calls"] == 1 and m["broker_target_avg"] == 1850.0 and m["analyst_buy_pct"] == 80.0 and m["target_upside_pct"] == 10.0
    assert metrics(None, [], None)["news_sentiment"] is None
    print("ok")
