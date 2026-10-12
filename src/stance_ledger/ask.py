"""Ask your own question to one arm's memory, as of a date (uses your Anthropic key)."""

from __future__ import annotations

from stance_ledger import ledger, llm, rag, summary
from stance_ledger.brief import actor_map_text, propositions
from stance_ledger.bundles import step_end
from stance_ledger.config import MODELS

SYSTEM = """You answer questions about a developing news story in Serbia using only the memory \
you are given, as of its date. Attribute every stance to who stated it; never say who is right; \
if the memory does not cover the question, say so.

Actor map:
{actors}"""


def ask(question: str, step: int, arm: str, topic: str | None = None) -> str:
    topics = [topic] if topic else ["T1", "T2", "T3", "T4"]
    if arm == "rag":
        mem = rag.context(question, step_end(step))
    elif arm == "ledger":
        recs = ledger.load()
        mem = "\n\n".join(ledger.render(recs, t, step) for t in topics)
    else:
        mem = "\n\n".join(summary.memory_at(t, arm.split("_")[1], step) for t in topics)
    props = "\n".join(f"{p['id']}: {p['text']}" for p in propositions() if p["topic"] in topics)
    user = (f"Date: {step_end(step):%Y-%m-%d}\nPropositions tracked:\n{props}\n\nMemory:\n{mem}"
            f"\n\nQuestion: {question}")
    return llm.call("ask", llm.params(MODELS["reader"], SYSTEM.format(actors=actor_map_text()),
                                      user, max_tokens=1500))
