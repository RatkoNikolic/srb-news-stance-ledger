"""Rolling-summary memory: at every step with news, the model rewrites the topic summary from
the previous summary plus the new bundle. Two variants with the same input and length cap:

- unbriefed: the memory most agents keep ("keep a running summary of this topic");
- briefed: the same, with the topic brief (propositions, actor map, attribution rules).

Each topic x variant is one sequential chain; chains run in parallel. Output:
runs/summary/<variant>/<topic>.jsonl, one line per step: {step, end, summary}. Resumable.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from stance_ledger import llm
from stance_ledger.brief import brief
from stance_ledger.bundles import N_STEPS, bundle, step_end
from stance_ledger.config import MODELS, RUNS
from stance_ledger.topics import TOPICS

OUT = RUNS / "summary"
CAP_WORDS = 600

UNBRIEFED = f"""You maintain an agent's memory of a developing news story: a running summary \
that an analyst will rely on later. You receive the current summary and the newest news \
excerpts (Serbian, Latin script). Write the updated summary in English. Keep it under \
{CAP_WORDS} words. Output only the summary."""

BRIEFED = UNBRIEFED + "\n\n" + "The summary must track the propositions below.\n\n{brief}"


def excerpts(ws: list[dict]) -> str:
    return "\n\n".join(f"[{w['known_at']:%Y-%m-%d}] {w['title']}\n{w['text']}" for w in ws)


def chain(topic: str, variant: str) -> int:
    path = OUT / variant / f"{topic}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    current = done[-1]["summary"] if done else "(empty: no news yet)"
    start = done[-1]["step"] + 1 if done else 1
    system = BRIEFED.format(brief=brief(topic)) if variant == "briefed" else UNBRIEFED
    calls = 0
    for k in range(start, N_STEPS + 1):
        ws = bundle(topic, k)
        if ws:
            user = (f"Story: {TOPICS[topic].name} (Serbia, from November 2024)\n\n"
                    f"Current summary:\n{current}\n\nNew excerpts, up to "
                    f"{step_end(k):%Y-%m-%d}:\n{excerpts(ws)}")
            current = llm.call(f"summary_{variant}",
                               llm.params(MODELS["summary"], system, user, max_tokens=2000))
            calls += 1
        with path.open("a") as f:
            f.write(json.dumps({"step": k, "end": step_end(k).isoformat(),
                                "updated": bool(ws), "summary": current},
                               ensure_ascii=False) + "\n")
    return calls


def run(topics=("T1", "T2", "T3", "T4"), variants=("unbriefed", "briefed")) -> dict:
    jobs = [(t, v) for t in topics for v in variants]
    bundle(topics[0], 1)          # load the bundles once, before the threads start
    with ThreadPoolExecutor(len(jobs)) as ex:
        res = list(ex.map(lambda tv: chain(*tv), jobs))
    return dict(zip([f"{t}/{v}" for t, v in jobs], res))


def memory_at(topic: str, variant: str, step: int) -> str:
    path = OUT / variant / f"{topic}.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    best = [r for r in rows if r["step"] <= step]
    return best[-1]["summary"] if best else "(empty: no news yet)"
