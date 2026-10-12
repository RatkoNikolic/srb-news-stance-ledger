"""The judge (Claude Opus 5.5, batch), used for two things only:

1. attribution survival: at 13 snapshots (every 7 steps, about two weeks), for each memory arm
   and topic, every gold stance known by then is labelled against the memory text:
   attributed | stated_as_fact | misattributed | lost;
2. stated as fact: whether a reader's prose answer states a contested proposition (or its
   negation) as fact in its own voice.

Everything else is scored deterministically (score.py).
"""

from __future__ import annotations

import json

from stance_ledger import ledger, llm, summary
from stance_ledger.answer import gold
from stance_ledger.brief import propositions
from stance_ledger.bundles import step_end
from stance_ledger.config import MODELS, RUNS

OUT = RUNS / "judge"
SNAPSHOTS = list(range(7, 92, 7))      # 13 snapshots, every 14 days
MEMORY_ARMS = ["summary_unbriefed", "summary_briefed", "ledger"]
CONTESTED = {"P1", "P2", "P5", "P6", "P7"}

SURVIVAL_SYSTEM = """You audit an AI agent's memory of a news story. You get the memory text and \
a list of stances that actors stated in the news before the memory's date. For each stance \
decide how the memory represents it:
- attributed: the memory says that this actor (or clearly the same body) holds or held this \
stance;
- stated_as_fact: the memory states the stance's content as fact in its own voice, without \
attributing it to anyone;
- misattributed: the memory gives this stance to a different actor;
- lost: the memory does not contain it.
Judge only representation, never whether the stance is true. Return one label per stance id."""

SURVIVAL_SCHEMA = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {
        "gid": {"type": "string"},
        "label": {"type": "string", "enum": ["attributed", "stated_as_fact", "misattributed",
                                             "lost"]}},
    "required": ["gid", "label"], "additionalProperties": False}}},
    "required": ["labels"], "additionalProperties": False}

FACT_SYSTEM = """You check whether an answer about a contested news matter states the \
proposition, or its negation, as fact in the answer's own voice (rather than attributing it to \
someone). Answer: affirms_as_fact (states the proposition is true), denies_as_fact (states it \
is false), or attributed_only (only reports who said what, or takes no position)."""

FACT_SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": [
    "affirms_as_fact", "denies_as_fact", "attributed_only"]}}, "required": ["verdict"],
    "additionalProperties": False}


def stance_line(g: dict) -> str:
    v = g.get("value")
    val = (f" value {v['low']}-{v['high']}" if isinstance(v, dict)
           else f" value {v}" if v else "")
    return (f"{g['gid']}: actor {g['actor']} | proposition {g['proposition']} | "
            f"stance {g['stance']}{val} | {g['paraphrase_en']}")


def _memory(arm: str, topic: str, k: int, recs: list[dict]) -> str:
    if arm == "ledger":
        return ledger.render(recs, topic, k)
    return summary.memory_at(topic, arm.split("_")[1], k)


def survival() -> list[dict]:
    recs, golds = ledger.load(), gold()
    reqs, known_ids = {}, {}
    for arm in MEMORY_ARMS:
        for topic in ("T1", "T2", "T3", "T4"):
            props = "\n".join(f"{p['id']}: {p['text']}" for p in propositions(topic))
            for k in SNAPSHOTS:
                known = [g for g in golds if g["gid"].startswith(topic) and g["t"] <= step_end(k)]
                if not known:
                    continue
                cid = f"{arm}__{topic}__{k}"
                known_ids[cid] = [g["gid"] for g in known]
                user = (f"Memory date: {step_end(k):%Y-%m-%d}\nPropositions:\n{props}\n\n"
                        f"Memory:\n{_memory(arm, topic, k, recs)}\n\nStances:\n"
                        + "\n".join(stance_line(g) for g in known))
                reqs[cid] = llm.params(MODELS["judge"], SURVIVAL_SYSTEM, user, SURVIVAL_SCHEMA,
                                       max_tokens=16000, effort="medium")
    est = len(reqs) * llm.usd(MODELS["judge"], 4000, 3500, batch=True) * 1.3
    res = llm.batch("judge_survival", reqs, OUT / "survival_batch.json", est)
    out = []
    for cid, text in res.items():
        arm, topic, k = cid.split("__")
        labels = {x["gid"]: x["label"] for x in json.loads(text)["labels"]
                  if x["gid"] in known_ids[cid]}
        out.append({"arm": arm, "topic": topic, "step": int(k), "labels": labels})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "survival.json").write_text(json.dumps(out, indent=0))
    return out


def stated_as_fact() -> dict:
    answers = json.loads((RUNS / "answers" / "answers.json").read_text())
    props = {p["id"]: p for p in propositions()}
    reqs, ids = {}, {}
    for key, ans in answers.items():
        pid = key.split("|")[1]
        if pid not in CONTESTED:
            continue
        cid = key.replace("|", "__")
        ids[cid] = key
        reqs[cid] = llm.params(MODELS["judge"], FACT_SYSTEM,
                               f"Proposition: {props[pid]['text']}\n\nAnswer:\n{ans['answer']}",
                               FACT_SCHEMA, max_tokens=8000, effort="low")
    est = len(reqs) * llm.usd(MODELS["judge"], 600, 800, batch=True) * 1.3
    res = llm.batch("judge_fact", reqs, OUT / "stated_as_fact_batch.json", est)
    out = {ids[c]: json.loads(v)["verdict"] for c, v in res.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stated_as_fact.json").write_text(json.dumps(out, indent=0))
    return out
