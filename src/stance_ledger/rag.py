"""The RAG arm: no memory, search at question time. BM25 over 3-sentence passages of the
subset's articles, with prefix stemming (the first 6 characters of each token, a standard
baseline for Slavic languages that needs no lemmatiser), a hard filter on knowledge time,
wire-copy collapse, at most 3 passages per outlet, and the passages ordered by date. IDF is
computed once on the whole subset: a leak of corpus statistics only, never of documents.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from functools import cache

import duckdb

from stance_ledger.prepare import ARTICLES
from stance_ledger.windows import article_text, knowledge_time, norm_hash, sentences

_TOK = re.compile(r"\w+")
K1, B = 1.2, 0.75
PASSAGES, PER_OUTLET, CAP_WORDS = 8, 3, 600


def stems(text: str) -> list[str]:
    return [t[:6] for t in _TOK.findall(text.lower()) if len(t) > 2]


class Index:
    def __init__(self, event_ids: set[str]):
        rows = duckdb.sql(f"select * from '{ARTICLES}'").to_arrow_table().to_pylist()
        self.p: list[dict] = []
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for a in rows:
            if a["event_id"] not in event_ids:
                continue
            text = article_text(a)
            spans = sentences(text)
            kt, _ = knowledge_time(a["published_at"], a.get("title") or "")
            for i in range(0, len(spans), 3):
                s, e = spans[i][0], spans[min(i + 2, len(spans) - 1)][1]
                pid = len(self.p)
                body = text[s:e]
                tf = Counter(stems(body))
                self.p.append({"event_id": a["event_id"], "outlet_id": a["outlet_id"],
                               "url": a["url"], "known_at": kt, "title": a["title"] or "",
                               "text": body, "len": sum(tf.values()), "dup": norm_hash(body)})
                for term, n in tf.items():
                    self.post[term].append((pid, n))
        self.avg = sum(x["len"] for x in self.p) / max(1, len(self.p))
        self.idf = {t: math.log(1 + (len(self.p) - len(v) + 0.5) / (len(v) + 0.5))
                    for t, v in self.post.items()}

    def search(self, query: str, until, n: int = PASSAGES) -> list[dict]:
        score: dict[int, float] = defaultdict(float)
        for t in set(stems(query)):
            for pid, tf in self.post.get(t, ()):
                if self.p[pid]["known_at"] <= until:
                    L = self.p[pid]["len"]
                    score[pid] += self.idf[t] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * L / self.avg))
        out, dups, per = [], set(), Counter()
        for pid, _ in sorted(score.items(), key=lambda kv: -kv[1]):
            p = self.p[pid]
            if p["dup"] in dups or per[p["outlet_id"]] >= PER_OUTLET:
                continue
            dups.add(p["dup"])
            per[p["outlet_id"]] += 1
            out.append(p)
            if len(out) >= n:
                break
        return sorted(out, key=lambda p: p["known_at"])


@cache
def index() -> Index:
    ids = {r[0] for r in duckdb.sql("select distinct event_id from 'local/bundles.parquet'")
           .fetchall()}
    return Index(ids)


def context(query: str, until) -> str:
    parts, words = [], 0
    for p in index().search(query, until):
        block = f"[{p['known_at']:%Y-%m-%d}] {p['title']}\n{p['text']}"
        w = len(block.split())
        if words + w > CAP_WORDS and parts:
            break
        parts.append(block)
        words += w
    return "\n\n".join(parts) if parts else "(no articles found)"
