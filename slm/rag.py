"""News & Catalyst RAG: per signal ticker, retrieve the passages that matter from headlines, NSE filings and the earnings
record, rank them with BM25 against a catalyst query and a risk query, and tag red flags / supportive items.
The model sees only the retrieved passages (with source and date), never the whole feed."""
import math
import re
from collections import Counter

CATALYST_Q = "results profit beat estimates surprise order win contract bags secures guidance upgrade raises record revenue growth expansion"
RISK_Q = ("auditor resignation resigns downgrade credit rating fraud forensic irregularities siphon sebi rbi penalty order ban notice "
          "probe raid pledge pledged governance default insolvency licence cancelled whistleblower")
RED_FLAG = re.compile(
    r"auditor\w*\s+(resign|quit|exit)|resign\w*\s+as\s+(statutory\s+)?auditor|(credit|debt|bond|ncd|crisil|icra|care|moody|fitch|"
    r"s&p|india ratings)\b.{0,40}downgrad|downgrad\w*.{0,40}\b(credit|debt|bonds?|ncd|rating)|fraud|forensic|siphon|"
    r"accounting\s+(irregular|lapse)|sebi\s+(order|bans?|barr|penal|show.cause|notice|probe|action)|pledge|governance\s+(issue|concern|lapse)|"
    r"\bdefault|insolven|\bed\s+(raid|probe)|income.tax\s+(raid|search)|whistle.?blow|rbi\s+(cancel|bans?|penal|restrict|curb|imposes)|"
    r"licen[cs]e\s+(cancel|revok|suspend)|(cancel|revok|suspend)\w*\s+.{0,30}licen[cs]e", re.I)
SUPPORTIVE = re.compile(r"\bbeats?\b|order\s+(win|worth|inflow)|(bags|wins|secures|receives|bagged|won)\b.{0,30}(order|contract)|upgrad|"
                        r"raises?\s+(guidance|outlook)|record\s+(profit|revenue|sales)|profit\s+(jumps|surges|rises|soars|up)|strong\s+q\d", re.I)
TOKEN = re.compile(r"[a-z0-9]+")


def bm25(docs, query, k1=1.5, b=0.75):
    """BM25 score of each doc (list of strings) for the query."""
    toks = [TOKEN.findall(d.lower()) for d in docs]
    if not toks:
        return []
    avg = sum(map(len, toks)) / len(toks) or 1
    df = Counter(t for ts in toks for t in set(ts))
    n, q = len(toks), TOKEN.findall(query.lower())
    out = []
    for ts in toks:
        tf = Counter(ts)
        out.append(sum(math.log(1 + (n - df[t] + .5) / (df[t] + .5)) * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(ts) / avg))
                       for t in q if t in tf))
    return out


def _verdict(surprise):
    return "beat" if surprise > 5 else "miss" if surprise < -5 else "in line"  # ±5% band: a 1% beat is noise


def documents(company, symbol, news, filings, earnings):
    """One passage per item, keeping only headlines that name the company (a ticker search drags in unrelated stories)."""
    word = re.sub(r"\b(ltd|limited|the|india|of|and)\b\.?", "", company, flags=re.I).split()[0].lower()
    docs = [{"source": f"news · {x['source'] or 'Google News'}", "date": x["date"], "text": x["title"]}
            for x in news if word in x["title"].lower() or symbol.lower() in x["title"].lower()]
    docs += [{"source": "NSE filing", "date": x["date"], "text": f"{x['subject']}: {x['text']}".strip(": ")} for x in filings]
    if earnings and earnings.get("surprise_pct") is not None:
        docs.append({"source": "earnings (Yahoo)", "date": earnings["date"],
                     "text": f"Quarterly EPS {earnings['eps_reported']} vs estimate {earnings['eps_estimate']}: surprise "
                             f"{earnings['surprise_pct']}% ({_verdict(earnings['surprise_pct'])})"})
    return docs


def retrieve(docs, earnings, k=3):
    """Top-k catalyst and risk passages, the red flags and supportive items among them, and the earnings surprise."""
    texts = [d["text"] for d in docs]
    pick = lambda scores: [docs[i] | {"score": round(s, 2)} for i, s in sorted(enumerate(scores), key=lambda x: -x[1])[:k] if s > 0]
    flags = [d for d in docs if RED_FLAG.search(d["text"])]
    good = [d for d in docs if SUPPORTIVE.search(d["text"]) and not RED_FLAG.search(d["text"])]
    surprise = earnings and earnings.get("surprise_pct")
    return {"catalyst_passages": pick(bm25(texts, CATALYST_Q)), "risk_passages": pick(bm25(texts, RISK_Q)),
            "red_flags": [f"{d['text'][:140]} ({d['source']}, {d['date']})" for d in flags[:3]],
            "supportive": [f"{d['text'][:140]} ({d['source']}, {d['date']})" for d in good[:3]],
            "earnings_surprise": earnings, "earnings_beat": surprise is not None and surprise > 5,
            "earnings_miss": surprise is not None and surprise < -5, "documents_searched": len(docs)}
