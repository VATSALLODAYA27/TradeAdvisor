"""BullBear: the site's AI guide. Gemini chat with tools that read the app's data and move around the site, plus voice.

Settings follow the user's desktop mascot (EDITH): Gemini model chain, 2048-token replies, short chat-bubble answers,
voice "Algenib" at speed 1 with an 8 dB low-shelf bass boost at 250 Hz. No Streamlit here: ask() returns the reply and
the actions for the UI to apply (open a tab, show an analysis). Key: GEMINI_API_KEY, else GOOGLE_API_KEY.
"""
import base64
import io
import json
import math
import os
import re
import wave
from datetime import date
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

import advisor
import data

CFG = {  # from the desktop mascot's config.json / main.js, renamed for this site
    "name": "Taursa",  # Taurus (the bull) + Ursa (the bear)
    "model": "gemini-3.6-flash",
    "fallbackModels": ["gemini-3.5-flash", "gemini-3.1-flash-lite"],
    "maxTokens": 2048,
    "voice": "Algenib",
    "voiceSpeed": 1,
    "voiceBass": 8,  # dB, low-shelf at 250 Hz like the desktop mascot's Web Audio filter
    "ttsModels": ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"],
}
BASE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
TABS = ["Analyze", "Opportunities", "AI Portfolio Desk", "Order Blocks", "Backtest", "Paper Trading", "Learn", "Option strategies", "Market", "News",
        "Commodities", "IPO", "Mutual Funds", "Brief", "Journal", "Rules", "Indicators"]  # grouped ones resolve in app.GROUPED
STOCK_ADVISORS = [n for n in advisor.RULES if n not in advisor.OWN_TAB and not n.startswith("vatsal")]

SYSTEM = f"""You are {CFG['name']}, the friendly bull-and-bear guide of TradeAdvisor, a rule-based market research site for
Indian stocks (NSE/BSE). Your replies appear in a small chat bubble and are read aloud, so keep them short and plain:
usually under 80 words, no headings, no tables, minimal markdown. Be warm and direct.

How the site works (tabs, left to right):
- Analyze: type a symbol or company name, click Get verdict. Every advisor (intraday, swing, longterm, options, hedge,
  breakout) checks the user's own rules; shows price, chart, signals, trade setups, results (QoQ/YoY, beat or miss),
  shareholding (promoters, FIIs, DIIs, public), option picks and an AI summary.
- Opportunities: scans a universe of shares for setups meeting the user's minimum reward:risk.
- Order Blocks: institutional order blocks and liquidity zones. Strategies: option strategy payoffs.
- Backtest: replays one advisor's rules on past daily candles. Market: NSE scanners and sector heatmap.
- News: market headlines, a stock's news mood, analyst ratings and targets, news-based verdict.
- Commodities, IPO (open/upcoming issues with GMP, subscription, financials, broker reviews, verdict; recently listed),
  Mutual Funds (rank a category, compare with benchmarks), Brief (morning brief PDF), Journal (the user's trades),
  Rules (edit the rules behind every verdict), Indicators (indicator periods).
Verdicts are BUY / SELL / AVOID etc. and come ONLY from the user's own rules; you explain them, never change them.
Describe only the features listed above; if asked for something the site doesn't do (e.g. fund holdings, placing
orders), say so plainly.

Use the tools for any live number; never invent prices, targets or verdicts. When a question needs several lookups,
call all the tools you need in the same turn; they run together. When the user asks for a report, document or PDF on a
stock, use create_report: it builds a PDF on the TradeAdvisor letterhead with a disclaimer, and a "Download report"
button appears next to you. To show the user something, open the tab or
run the analysis with a tool, then tell them what you did. If asked "should I buy/sell", give the site's rule-based
verdict and the key numbers, and say you are not a SEBI-registered adviser and this is not investment advice."""

TOOLS = [{"function_declarations": [
    {"name": "open_tab", "description": "Open a tab of the website for the user.",
     "parameters": {"type": "object", "properties": {"tab": {"type": "string", "enum": TABS}}, "required": ["tab"]}},
    {"name": "analyze_stock", "description": "Run the full analysis for a stock or index (symbol or company name), show it on the "
     "Analyze tab, and return price and every advisor's verdict.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "e.g. RELIANCE, jain irrigation, NIFTY"}},
                    "required": ["query"]}},
    {"name": "stock_research", "description": "A stock's latest results (QoQ/YoY growth, EPS vs estimate, next results date), "
     "shareholding (promoters/FII/DII/public and changes), analyst ratings and targets, and news mood with top headlines.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "create_report", "description": "Build a downloadable PDF report on the TradeAdvisor letterhead for a stock: "
     "snapshot, chart, every verdict and rule, results, shareholding, valuation, trade setups and a disclaimer.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "symbol or company name"}},
                    "required": ["query"]}},
    {"name": "ipo_list", "description": "Open and upcoming IPOs with GMP, subscription, key financials and the IPO verdict.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "market_overview", "description": "NIFTY 50, India VIX, advance/decline, FII/DII flows and the latest market headlines.",
     "parameters": {"type": "object", "properties": {}}},
]}]


def key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _post(body, models, k, timeout=60):
    """generateContent on the first model that answers; quotas are per model, so 404/429/5xx fall through."""
    err = "No model configured."
    for m in models:
        r = requests.post(BASE.format(m), headers={"x-goog-api-key": k}, json=body, timeout=timeout)
        if r.ok:
            return r.json(), None
        msg = (r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}).get("message", f"HTTP {r.status_code}")
        err = {401: "Google rejected the API key.", 403: "Google denied the request (check the key).",
               429: "Free-tier limit reached. Wait a minute and try again."}.get(r.status_code, msg)
        if r.status_code in (400, 401, 403) and "model" not in msg.lower():
            break  # a bad key or request won't work on the next model either
    return None, err


def _symbol(query):
    from setups import parse_query
    sym = parse_query(query)[0]
    if " " in sym and (found := data.resolve(sym)):
        return found
    return sym, "NSE"


def _clip(m, keys):
    return {k: (round(v, 2) if isinstance(v, float) else v) for k in keys if (v := m.get(k)) is not None}


def run_tool(name, args):
    """-> (result for the model, action for the UI or None)."""
    if name == "open_tab":
        tab = args.get("tab")
        return ({"opened": tab}, {"goto": tab}) if tab in TABS else ({"error": f"no tab {tab}"}, None)
    if name == "analyze_stock":
        sym, ex = _symbol(args.get("query", ""))
        out = advisor.build(STOCK_ADVISORS).invoke({"symbol": sym, "exchange": ex, "use_llm": False, "verdicts": {}})
        m = out["metrics"]
        if "close" not in m and "price" not in m:
            found = data.resolve(args.get("query", ""))
            if not found:
                return {"error": f"couldn't find {args.get('query')}"}, None
            sym, ex = found
            out = advisor.build(STOCK_ADVISORS).invoke({"symbol": sym, "exchange": ex, "use_llm": False, "verdicts": {}})
            m = out["metrics"]
        result = {"symbol": sym, "exchange": ex, **_clip(m, ["price", "close", "day_change_pct", "rsi", "high_52w", "low_52w", "pe"]),
                  "verdicts": {n: v["verdict"] for n, v in out["verdicts"].items()}}
        return result, {"goto": "Analyze", "result": out | {"order": STOCK_ADVISORS}, "symbol": sym}
    if name == "create_report":
        import yfinance as yf

        import report
        import results
        result, action = run_tool("analyze_stock", args)
        if "error" in result:
            return result, None
        sym, out = action["symbol"], action["result"]
        res, rm = results.summary(sym)
        tk = yf.Ticker(data.yf_symbol(sym, out["exchange"]))
        d = tk.history(period="2y")
        try:
            name = tk.info.get("longName") or sym
        except Exception:
            name = sym
        pdf = report.build(out, d, name, res, rm)
        fname = f"{sym}_TradeAdvisor_report_{date.today():%Y-%m-%d}.pdf"
        return ({"report": "ready", "file": fname, "pages_note": "download button is next to Taursa", **result},
                action | {"download": {"name": fname, "data": pdf}})
    if name == "stock_research":
        import news
        import results
        sym, _ = _symbol(args.get("query", ""))
        _, rm = results.summary(sym)
        n = news.stock(sym)
        res = {"symbol": sym, "name": n["name"], **_clip(rm, rm.keys()), **_clip(n["metrics"], n["metrics"].keys()),
               "headlines": [f"{x['title']} ({x['source']})" for x in n["headlines"][:5]]}
        if (sec := advisor.RULES.get("news")):
            res["news_verdict"] = advisor.verdict(sec, n["metrics"])["verdict"]
        return res, None
    if name == "ipo_list":
        import ipo
        sec = advisor.RULES.get("ipo")
        rows = []
        for x in ipo.all_ipos():
            m = x["metrics"]
            rows.append({"company": x["row"]["companyName"], "status": x["row"].get("status"), "closes": x["row"].get("issueEndDate"),
                         **_clip(m, ["ipo_price", "ipo_gmp_pct", "ipo_sub_total", "ipo_revenue_growth", "ipo_pat_cr", "ipo_roe",
                                     "ipo_pe", "ipo_broker_subscribe", "ipo_broker_avoid"]),
                         "verdict": advisor.verdict(sec, m)["verdict"] if sec else None})
        return {"ipos": rows}, {"goto": "IPO"}
    if name == "market_overview":
        import news
        m = data.market_metrics()
        items, _ = news.market(8)
        return {**_clip(m, m.keys()), "headlines": [x["title"] for x in items]}, None
    return {"error": f"unknown tool {name}"}, None


def ask(history, text, context="", audio=None):
    """One user turn. history: [{'role': 'user'|'model', 'text': str}]. audio: (bytes, mime) of a spoken question.
    Returns (reply, actions, transcript or None). Tool calls run here, up to 4 rounds."""
    k = key()
    if not k:
        return "I need a Gemini API key to talk. Add GEMINI_API_KEY in the app's secrets.", [], None
    models = [CFG["model"], *CFG["fallbackModels"]]
    transcript = None
    if audio:  # transcribe first, so the chat shows what was asked
        got, err = _post({"contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": audio[1], "data": base64.b64encode(audio[0]).decode()}},
            {"text": "Transcribe this question exactly (Indian English, stock names). Reply with the words only."}]}]}, models, k)
        if err:
            return f"I couldn't hear that: {err}", [], None
        transcript = text = "".join(p.get("text", "") for p in got["candidates"][0]["content"]["parts"]).strip()
    contents = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history[-10:]]
    contents.append({"role": "user", "parts": [{"text": (f"[Context: {context}]\n" if context else "") + text}]})
    actions = []
    for _ in range(4):
        got, err = _post({"system_instruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "tools": TOOLS,
                          "generationConfig": {"maxOutputTokens": CFG["maxTokens"]}}, models, k)
        if err:
            return f"Sorry, {err}", actions, transcript
        content = got["candidates"][0].get("content", {"role": "model", "parts": []})
        calls = [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]
        if not calls:
            reply = "".join(p.get("text", "") for p in content.get("parts", []) if not p.get("thought")).strip()
            return reply or "Done.", actions, transcript
        contents.append(content)  # sent back as-is: newer models attach thought signatures to their calls

        def one(c):
            try:
                return run_tool(c["name"], c.get("args", {}))
            except Exception as ex:
                return {"error": f"{type(ex).__name__}: {ex}"}, None

        with ThreadPoolExecutor(min(4, len(calls))) as pool:  # the orchestrator: independent lookups run together
            done = list(pool.map(one, calls))
        parts = []
        for c, (result, action) in zip(calls, done):
            if action:
                actions.append(action)
            parts.append({"functionResponse": {"name": c["name"], "response": json.loads(json.dumps(result, default=str))}})
        contents.append({"role": "user", "parts": parts})
    return "That took too many steps; please ask in a simpler way.", actions, transcript


def bass(pcm, rate, gain_db, f0=250.0):
    """RBJ low-shelf biquad (same as the browser's 'lowshelf' filter) on int16 samples; peaks are kept from clipping."""
    if not gain_db:
        return pcm
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * f0 / rate
    alpha = math.sin(w0) / 2 * math.sqrt(2)
    c, sa = math.cos(w0), 2 * math.sqrt(a) * alpha
    b0, b1, b2 = a * ((a + 1) - (a - 1) * c + sa), 2 * a * ((a - 1) - (a + 1) * c), a * ((a + 1) - (a - 1) * c - sa)
    a0, a1, a2 = (a + 1) + (a - 1) * c + sa, -2 * ((a - 1) + (a + 1) * c), (a + 1) + (a - 1) * c - sa
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    x = pcm.astype(np.float64)
    y = np.empty_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, xi in enumerate(x):  # shortcut: plain loop (~0.2 s for 10 s of speech); vectorise with scipy.signal.lfilter if it matters
        yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, xi, y1, yi
        y[i] = yi
    peak = np.abs(y).max() if len(y) else 0
    if peak > 32000:
        y *= 32000 / peak
    return y.astype(np.int16)


def _wav(pcm, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def speak(text):
    """Reply text -> WAV bytes in the mascot's voice, or None (no key, quota, or no audio)."""
    k = key()
    clean = re.sub(r"[*_#`>]|\[(.*?)\]\(.*?\)", r"\1", text or "").strip()[:2000]
    if not k or not clean:
        return None
    got, err = _post({"contents": [{"parts": [{"text": clean}]}], "generationConfig": {
        "responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": CFG["voice"]}}}}},
        CFG["ttsModels"], k, timeout=90)
    if err:
        return None
    for p in got["candidates"][0]["content"]["parts"]:
        d = p.get("inlineData") or p.get("inline_data")
        if not d:
            continue
        raw = base64.b64decode(d["data"])
        mime = d.get("mimeType") or d.get("mime_type", "")
        if mime.startswith("audio/wav"):
            return raw
        if (rate := re.search(r"rate=(\d+)", mime)) and "L16" in mime.upper():  # raw 16-bit PCM
            r = int(rate.group(1))
            return _wav(bass(np.frombuffer(raw, dtype="<i2"), r, CFG["voiceBass"]), r)
    return None


if __name__ == "__main__":  # offline self-checks
    tone = np.full(4000, 1000, dtype=np.int16)  # DC: a low shelf of +8 dB multiplies it by 10^(8/20) = 2.51
    assert abs(bass(tone, 24000, 8)[-1] / 1000 - 10 ** (8 / 20)) < 0.02
    hi = (np.sin(np.arange(4000) * math.pi * 0.9) * 1000).astype(np.int16)  # near Nyquist: a low shelf leaves it ~unchanged
    assert abs(np.abs(bass(hi, 24000, 8)[2000:]).max() / 1000 - 1) < 0.05
    w = _wav(tone, 24000)
    assert w[:4] == b"RIFF" and wave.open(io.BytesIO(w)).getframerate() == 24000
    assert run_tool("open_tab", {"tab": "IPO"}) == ({"opened": "IPO"}, {"goto": "IPO"}) and run_tool("open_tab", {"tab": "x"})[1] is None
    calls = []  # one tool round, then a text answer: the loop must send the tool result back and return the text
    replies = iter([{"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": "open_tab", "args": {"tab": "News"}}}]}}]},
                    {"candidates": [{"content": {"role": "model", "parts": [{"text": "Opened News for you."}]}}]}])
    _real, _key = _post, key
    _post = lambda body, models, k, timeout=60: (calls.append(body), (next(replies), None))[1]
    key = lambda: "test"
    reply, actions, _ = ask([], "show me the news")
    assert reply == "Opened News for you." and actions == [{"goto": "News"}]
    assert calls[1]["contents"][-1]["parts"][0]["functionResponse"]["response"] == {"opened": "News"}
    _post, key = _real, _key
    print("ok")
