"""The stance ledger: append-only stance records -> per-actor timelines -> rendered memory.

Everything here is deterministic: no model decides what is current. For each (actor,
proposition), records ordered by knowledge time form a timeline; a different stance from the
same actor is a `stance change`, the same stance is `restated`. Different actors are never
merged: disagreement stays as separate lines. Rendering is a template, capped to the same
length as the summaries, so the ledger memory cannot drift.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime

from stance_ledger.brief import propositions, registry
from stance_ledger.config import RUNS

RECORDS = RUNS / "ledger" / "extract_records.jsonl"
MACUT = datetime(2025, 4, 16, tzinfo=UTC)
TERM_KEYED = {"ministry_education", "ministry_construction"}
CAP_WORDS = 600


def actor_key(actor: str, known_at: datetime) -> str:
    if actor in TERM_KEYED and known_at >= MACUT:
        return actor + "@macut"
    return actor


def actor_name(actor: str) -> str:
    base = actor.split("@")[0]
    for a in registry()[1]["fixed"]:
        if a["id"] == base:
            return a["name"]
    if ":" in base:
        return base.split(":", 1)[1].strip() or base
    return "unidentified actor" if base == "other" else base


def stance_value(r: dict) -> str:
    if r["stance"] != "value":
        return r["stance"]
    lo, hi = r.get("number_low"), r.get("number_high")
    if r.get("category") and not (lo or hi):
        return r["category"]
    if lo and hi and lo != hi:
        return f"{lo:,}-{hi:,}"
    return f"{lo or hi:,}" if (lo or hi) else "unspecified"


def same(a: str, b: str) -> bool:
    """Two stances are the same; numbers within 10% (or overlapping ranges) count as same."""
    if a == b:
        return True
    try:
        pa = [float(x.replace(",", "")) for x in a.split("-")]
        pb = [float(x.replace(",", "")) for x in b.split("-")]
    except ValueError:
        return False
    lo_a, hi_a, lo_b, hi_b = min(pa), max(pa), min(pb), max(pb)
    return (lo_a <= hi_b * 1.1 and lo_b <= hi_a * 1.1)


_TAIL = re.compile(r"[\s\]\}\)`·•]+$")


def load(path=RECORDS) -> list[dict]:
    recs = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    for r in recs:
        r["known_at"] = datetime.fromisoformat(r["known_at"])
        r["paraphrase_en"] = _TAIL.sub("", r["paraphrase_en"]).rstrip() or r["paraphrase_en"]
        if not r["paraphrase_en"].endswith((".", "?", "!", '"', "'")):
            r["paraphrase_en"] += "."
    return [r for r in recs if r["actor"] != "other"]


def _step_majority(rs: list[dict]) -> tuple[str, dict, set]:
    """The stance most independent outlets report for one actor in one step (ties: latest)."""
    votes: dict[str, set] = defaultdict(set)
    first: dict[str, dict] = {}
    for r in rs:
        st = stance_value(r)
        key = next((k for k in votes if same(k, st)), st)
        votes[key].add(r["outlet_id"])
        first.setdefault(key, r)
    best = max(votes, key=lambda k: (len(votes[k]), first[k]["known_at"]))
    return best, first[best], votes[best]


def timelines(recs: list[dict], step: int, min_outlets: int = 1) -> dict:
    """{proposition: {actor_key: [segment, ...]}} from records in steps <= step.

    min_outlets=2 is the "corroborated" ledger setting: a change of stance needs >= 2
    independent outlets reporting the new stance within its step.

    Consolidation (fixed before any scoring): within each 2-day step, an actor's stance is the
    one reported by the most independent outlets; a new segment starts only when that step
    majority differs from the current stance. Segment: {stance, since, last, outlets,
    paraphrase}."""
    by = defaultdict(lambda: defaultdict(list))
    for r in recs:
        if r["step"] <= step:
            by[(r["proposition"], actor_key(r["actor"], r["known_at"]))][r["step"]].append(r)
    tl: dict = defaultdict(dict)
    for (prop, key), steps in by.items():
        segs: list[dict] = []
        for k in sorted(steps):
            st, rec, outlets = _step_majority(steps[k])
            if segs and not same(segs[-1]["stance"], st) and len(outlets) < min_outlets:
                continue                 # an uncorroborated change: treated as noise
            if segs and same(segs[-1]["stance"], st):
                segs[-1]["last"] = rec["known_at"]
                segs[-1]["outlets"] |= outlets
            else:
                segs.append({"stance": st, "since": rec["known_at"], "last": rec["known_at"],
                             "outlets": set(outlets), "paraphrase": rec["paraphrase_en"],
                             "record_id": rec["record_id"]})
        tl[prop][key] = segs
    return tl


def render(recs: list[dict], topic: str, step: int, detailed: int = 2,
           min_outlets: int = 1) -> str:
    """Template rendering: per proposition, actors by number of independent reports; the
    `detailed` most-reported actors get a paraphrase, the rest one compact line; at most the
    last three earlier stances are listed. Capped at CAP_WORDS, shared equally."""
    tl = timelines(recs, step, min_outlets)
    active = [p for p in propositions(topic) if tl.get(p["id"])]
    budget = CAP_WORDS // max(1, len(active))
    text = []
    for p in active:
        block, words = [f"{p['id']}: {p['text']}"], len(p["text"].split())
        ranked = sorted(tl[p["id"]].items(),
                        key=lambda kv: -sum(len(s["outlets"]) for s in kv[1]))
        for i, (key, segs) in enumerate(ranked):
            cur = segs[-1]
            n = sum(len(s["outlets"]) for s in segs)
            line = f"  - {actor_name(key)}: {cur['stance']} (since {cur['since']:%Y-%m-%d}; {n} rep.)"
            if len(segs) > 1:
                earlier = "; ".join(f"{s['stance']} {s['since']:%m-%d}" for s in segs[-4:-1])
                line += f"; earlier {earlier}"
            if i < detailed:
                line += f". {cur['paraphrase']}"
            if words + len(line.split()) > budget and i > 0:
                block.append(f"  ({len(ranked) - i} less-reported actors omitted)")
                break
            block.append(line)
            words += len(line.split())
        text += block
    return "\n".join(text) if text else "(no stances recorded yet)"
