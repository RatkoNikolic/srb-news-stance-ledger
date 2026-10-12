"""Stance extraction for the ledger, in two batch passes over the bundle windows.

1. filter (Haiku 5.5): does the window report any actor's stance on one of the topic's
   propositions?
2. extract (Sonnet 5.5): the stance records, with the actor from the map, the stance, an
   English paraphrase. Only stances attributed to an actor; never the outlet's own voice.

Windows are shown with their publication date only (no outlet), so outlets cannot enter the
records. Records go to runs/ledger/records.jsonl (no article text: ids, offsets, hashes and
the English paraphrase).
"""

from __future__ import annotations

import json
import re

_JUNK = re.compile(r"(\s*[·•]\s*)+$")
_BRACKET = re.compile(r"\s*\([^)]*\)")

from stance_ledger import llm
from stance_ledger.brief import brief, propositions, registry
from stance_ledger.bundles import BUNDLES
from stance_ledger.config import MODELS, RUNS

OUT = RUNS / "ledger"

FILTER_SYSTEM = """You screen short excerpts of Serbian news (Latin script) for a research \
project. Answer whether the excerpt reports a stance that some actor (an institution, an \
official in their office, a party, a student assembly, an organisation, a foreign body) takes \
on one of the listed propositions. A stance is what the actor says is the case; a mere \
mention of the topic, a question or the outlet's own commentary is not a stance."""

FILTER_SCHEMA = {"type": "object", "properties": {"has_stance": {"type": "boolean"}},
                 "required": ["has_stance"], "additionalProperties": False}

EXTRACT_SYSTEM = """You extract stances from Serbian news excerpts (Latin script) into records \
for a stance ledger. For each actor in the excerpt who states a stance on one of the \
propositions, output one record. Rules:
- actor: an id from the actor map, or a listed prefix followed by an institution or \
organisation name only (never a person's name, not even in brackets). People count only through their office or party (a minister -> the \
ministry; an opposition MP -> the party). If the speaker fits nothing on the map, use "other" \
and do not name them.
- Only stances the excerpt attributes to the actor (quotes or reported speech). Ignore the \
outlet's own commentary and any stance the actor is merely accused of holding by someone else \
unless it is the other actor's own claim about the proposition (then record it for that \
other actor).
- stance: affirms | denies | partial | hedged for polar propositions; "value" for category \
propositions (fill category) and number propositions (fill number_low and number_high; leave \
category empty). Predictions made before an event are not stances.
- paraphrase_en: one neutral English sentence of what the actor said, naming no private \
person.
- If there is no stance, return an empty list.

"""


def _record_schema() -> dict:
    return {"type": "object", "properties": {"records": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "actor": {"type": "string"},
            "proposition": {"type": "string"},
            "stance": {"type": "string", "enum": ["affirms", "denies", "partial", "hedged",
                                                  "value"]},
            "category": {"type": "string"},
            "number_low": {"type": "integer"},
            "number_high": {"type": "integer"},
            "paraphrase_en": {"type": "string"},
        },
        "required": ["actor", "proposition", "stance", "paraphrase_en"],
        "additionalProperties": False}}},
        "required": ["records"], "additionalProperties": False}


def window_text(w: dict) -> str:
    return f"Published: {w['known_at']:%Y-%m-%d}\nTitle: {w['title']}\n\n{w['text']}"


def _windows() -> list[dict]:
    import duckdb
    return duckdb.sql(f"select * from '{BUNDLES}' order by known_at").to_arrow_table().to_pylist()


def run_filter(windows: list[dict] | None = None, tag: str = "filter") -> dict[str, bool]:
    windows = windows or _windows()
    reqs = {}
    for w in windows:
        props = "\n".join(f"- {p['id']}: {p['text']}" for p in propositions(w["topic"]))
        reqs[w["window_id"]] = llm.params(
            MODELS["filter"], FILTER_SYSTEM, f"Propositions:\n{props}\n\nExcerpt:\n{window_text(w)}",
            FILTER_SCHEMA, max_tokens=200)
    est = len(reqs) * llm.usd(MODELS["filter"], 900, 30, batch=True) * 1.3
    res = llm.batch(tag, reqs, OUT / f"{tag}_batch.json", est)
    out = {k: json.loads(v)["has_stance"] for k, v in res.items()}
    (OUT / f"{tag}.json").write_text(json.dumps(out))
    return out


_PERSONISH = re.compile(r"\b([A-ZČĆŠŽĐ][a-zčćšžđ]+)\s+([A-ZČĆŠŽĐ][a-zčćšžđ]+(?:ić|ović|ević))\b")


def _allowed_names() -> set[str]:
    _, a = registry()
    names = set()
    for x in a["fixed"]:
        names.update(re.findall(r"[A-ZČĆŠŽĐ][a-zčćšžđ]+", x["name"] + " " + x.get("holder", "")))
    return names


def scrub(text: str) -> str:
    """Replace Serbian-looking personal names that are not office-holders on the map."""
    ok = _allowed_names()
    return _PERSONISH.sub(lambda m: m.group(0) if m.group(2) in ok else "[person]", text)


def run_extract(windows: list[dict] | None = None, keep: dict[str, bool] | None = None,
                tag: str = "extract") -> list[dict]:
    windows = windows or _windows()
    keep = keep if keep is not None else json.loads((OUT / "filter.json").read_text())
    todo = [w for w in windows if keep.get(w["window_id"])]
    schema = _record_schema()
    reqs = {w["window_id"]: llm.params(MODELS["extract"], EXTRACT_SYSTEM + brief(w["topic"]),
                                       f"Excerpt:\n{window_text(w)}", schema, max_tokens=2000)
            for w in todo}
    est = len(reqs) * llm.usd(MODELS["extract"], 1300, 250, batch=True) * 1.3
    res = llm.batch(tag, reqs, OUT / f"{tag}_batch.json", est)
    by_id = {w["window_id"]: w for w in todo}
    valid = {p["id"]: p for p in propositions()}
    recs = []
    bad = []
    for wid, text in res.items():
        w = by_id[wid]
        try:
            parsed = json.loads(text)["records"]
        except (json.JSONDecodeError, KeyError):
            bad.append(wid)          # truncated output (max_tokens): counted, left out
            continue
        for i, r in enumerate(parsed):
            if r["proposition"] not in valid or valid[r["proposition"]]["topic"] != w["topic"]:
                continue
            recs.append({
                "record_id": f"{wid}-{i}", "window_id": wid, "event_id": w["event_id"],
                "topic": w["topic"], "step": w["step"], "url": w["url"],
                "known_at": w["known_at"].isoformat(), "start": w["start"], "end": w["end"],
                "window_sha256": w["window_sha256"], "dup_key": w["dup_key"],
                "outlet_id": w["outlet_id"],  # kept only to count independent reports
                "actor": _BRACKET.sub("", r["actor"]).strip(), "proposition": r["proposition"],
                "stance": r["stance"], "category": r.get("category"),
                "number_low": r.get("number_low"), "number_high": r.get("number_high"),
                "paraphrase_en": scrub(_JUNK.sub("", r["paraphrase_en"]).strip()),
            })
    (OUT / f"{tag}_unparsed.json").write_text(json.dumps(bad))
    path = OUT / f"{tag}_records.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    return recs
