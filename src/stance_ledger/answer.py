"""Questions at event-anchored checkpoints, answered by the same reader from each arm's memory.

For every proposition, checkpoints are the steps containing the day before, the day after and
7 days after each gold stance's first publication. One question per (proposition, step): every
actor's stated position as of then, and any change of stance. The reader (Sonnet 5.5) gets the
actor map and the memory of one arm; it returns JSON. Arms: summary_unbriefed, summary_briefed,
ledger, rag, closed_book.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from stance_ledger import ledger, llm, rag, summary
from stance_ledger.brief import actor_map_text, propositions, stance_text
from stance_ledger.bundles import N_STEPS, step_end, step_of
from stance_ledger.config import DATA, LOCAL, MODELS, RUNS
from stance_ledger.windows import BELGRADE

OUT = RUNS / "answers"
ARMS = ["summary_unbriefed", "summary_briefed", "ledger", "ledger_corroborated", "rag",
        "closed_book"]


def gold() -> list[dict]:
    rows = []
    for f in sorted((DATA / "gold").glob("T*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                g = json.loads(line)
                g["t"] = datetime.fromisoformat(g["first_published_at"])
                rows.append(g)
    return rows


def checkpoints() -> list[tuple[str, int]]:
    out = set()
    for g in gold():
        day = g["t"].astimezone(BELGRADE).replace(hour=23, minute=59)
        for dd in (-1, 1, 7):
            k = step_of(day + timedelta(days=dd))
            if 1 <= k <= N_STEPS:
                out.add((g["proposition"], k))
    return sorted(out)


SYSTEM = """You answer questions about a developing news story in Serbia, as of a given date, \
using only the memory you are given (the closed-book arm gets no memory and answers from \
what it knows, as of that date). Report every actor's stated position on the proposition, \
attributed, and any change in an actor's stance, without saying who is right. If the memory \
says nothing about the proposition, return empty lists.

Use actor ids from this map (or a listed prefix with an institution name; people only through \
their office or party):
{actors}"""

SCHEMA = {"type": "object", "properties": {
    "positions": {"type": "array", "items": {"type": "object", "properties": {
        "actor": {"type": "string"}, "stance": {"type": "string"},
        "since": {"type": "string"}}, "required": ["actor", "stance", "since"],
        "additionalProperties": False}},
    "changes": {"type": "array", "items": {"type": "object", "properties": {
        "actor": {"type": "string"}, "from_stance": {"type": "string"},
        "to_stance": {"type": "string"}}, "required": ["actor", "from_stance", "to_stance"],
        "additionalProperties": False}},
    "answer": {"type": "string"}},
    "required": ["positions", "changes", "answer"], "additionalProperties": False}


def question(p: dict, k: int) -> str:
    d = step_end(k) - timedelta(seconds=1)
    return (f"As of {d:%d %B %Y}: what is each actor's stated position on this proposition, "
            f"and has any actor's stance changed (from what to what)?\nProposition {p['id']}: "
            f"{p['text']}\nStance format: {stance_text(p)}. For numbers write e.g. 107000 or "
            f"275000-325000. 'since' is the date the stance was first stated (YYYY-MM-DD) or "
            f"'unknown'. 'answer': two or three sentences in plain English.")


def memory(arm: str, p: dict, k: int, recs: list[dict]) -> str:
    if arm == "summary_unbriefed":
        return summary.memory_at(p["topic"], "unbriefed", k)
    if arm == "summary_briefed":
        return summary.memory_at(p["topic"], "briefed", k)
    if arm == "ledger":
        return ledger.render(recs, p["topic"], k)
    if arm == "ledger_corroborated":          # a change needs 2 outlets, see ledger.timelines
        return ledger.render(recs, p["topic"], k, min_outlets=2)
    if arm == "rag":
        return rag.context(p["query_sr"], step_end(k))
    return ""


def build_requests(arms=ARMS) -> dict[str, dict]:
    recs = ledger.load()
    props = {p["id"]: p for p in propositions()}
    system = SYSTEM.format(actors=actor_map_text())
    reqs, mem = {}, {}
    for pid, k in checkpoints():
        p = props[pid]
        for arm in arms:
            m = memory(arm, p, k, recs)
            mem[f"{arm}|{pid}|{k}"] = m
            user = question(p, k) if arm == "closed_book" else f"Memory:\n{m}\n\n{question(p, k)}"
            reqs[f"{arm}|{pid}|{k}"] = llm.params(MODELS["reader"], system, user, SCHEMA, 3000)
    # contexts include retrieved article text (RAG): local only, never shipped
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "answer_contexts.json").write_text(json.dumps(mem, ensure_ascii=False))
    return reqs


def run(arms=ARMS, tag: str = "") -> dict:
    reqs = build_requests(arms)
    est = len(reqs) * llm.usd(MODELS["reader"], 2500, 500, batch=True) * 1.3
    ids = {k.replace("|", "__"): k for k in reqs}          # custom_id allows [A-Za-z0-9_-]
    res = llm.batch("answer", {i: reqs[k] for i, k in ids.items()},
                    OUT / f"answer{tag}_batch.json", est)
    out, bad = {}, []
    for i, v in res.items():
        try:
            out[ids[i]] = json.loads(v)
        except json.JSONDecodeError:
            bad.append(ids[i])
    (OUT / f"unparsed{tag}.json").write_text(json.dumps(bad))
    path = OUT / "answers.json"
    merged = json.loads(path.read_text()) if tag and path.exists() else {}
    merged.update(out)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=0))
    return {"requests": len(reqs), "answers": len(out)}
