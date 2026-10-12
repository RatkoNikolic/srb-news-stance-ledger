"""Sentence windows: each cue sentence with one sentence of context on each side.

Knowledge time is the article's publication time; live blogs (titles with *uživo*, *minut po
minut*, *blog*) carry entries written after their start, so their windows become known at
06:00 Belgrade time the next day. Exact duplicates (wire copies) are grouped by a hash of the
normalised window text; each group keeps every carrier, and the earliest copy represents it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from stance_ledger.topics import LIVE_BLOG, TOPICS, in_window

BELGRADE = ZoneInfo("Europe/Belgrade")
_SPLIT = re.compile(r"(?<=[.!?…\"”])\s+(?=[A-ZČĆŠŽĐ„\"“(])|\n+")
_NORM = re.compile(r"[^\w]+")


def sentences(text: str) -> list[tuple[int, int]]:
    """Character spans of sentences in `text`."""
    spans, start = [], 0
    for m in _SPLIT.finditer(text):
        if m.start() > start:
            spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def knowledge_time(published: datetime, title: str) -> tuple[datetime, bool]:
    if LIVE_BLOG.search(title or ""):
        local = published.astimezone(BELGRADE)
        nxt = (local + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        return nxt.astimezone(published.tzinfo), True
    return published, False


def norm_hash(text: str) -> str:
    return hashlib.sha256(_NORM.sub(" ", text.lower()).strip().encode()).hexdigest()[:16]


def article_text(a: dict) -> str:
    parts = [a.get("title") or "", a.get("lead") or "", a.get("body") or ""]
    return "\n".join(p for p in parts if p.strip())


def windows_for(a: dict) -> list[dict]:
    """All topic windows in one article."""
    text = article_text(a)
    low = text.lower()
    spans = sentences(text)
    kt, live = knowledge_time(a["published_at"], a.get("title") or "")
    out = []
    for topic, t in TOPICS.items():
        if not in_window(topic, a["published_at"]):
            continue
        hit = {i for i, (s, e) in enumerate(spans) if t.cue.search(low[s:e])}
        for i in sorted(hit):
            s = spans[max(i - 1, 0)][0]
            e = spans[min(i + 1, len(spans) - 1)][1]
            w = text[s:e]
            out.append({
                "window_id": hashlib.sha256(f"{a['event_id']}:{topic}:{s}".encode()).hexdigest()[:16],
                "event_id": a["event_id"], "topic": topic, "outlet_id": a["outlet_id"],
                "url": a["url"], "published_at": a["published_at"], "known_at": kt,
                "live_blog": live, "start": s, "end": e,
                "window_sha256": hashlib.sha256(w.encode()).hexdigest(),
                "dup_key": norm_hash(w), "title": a.get("title") or "", "text": w,
            })
    return out
