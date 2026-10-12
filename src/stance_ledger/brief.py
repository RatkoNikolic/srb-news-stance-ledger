"""The topic brief every briefed arm receives: propositions, stance values, the actor map and
the rules (attribute every stance, keep earlier stances, give no verdict). One text, so the
briefed summary, the ledger extractor and the readers see the same instructions."""

from __future__ import annotations

import json
from functools import cache

from stance_ledger.config import DATA
from stance_ledger.topics import TOPICS


@cache
def registry() -> tuple[dict, dict]:
    props = json.loads((DATA / "registry" / "propositions.json").read_text())
    actors = json.loads((DATA / "registry" / "actors.json").read_text())
    return props, actors


def propositions(topic: str | None = None) -> list[dict]:
    ps = registry()[0]["propositions"]
    return [p for p in ps if topic is None or p["topic"] == topic]


def actor_map_text() -> str:
    _, a = registry()
    lines = [f"- {x['id']}: {x['name']}" for x in a["fixed"]]
    lines += [f"- {k}<name>: {v}" for k, v in a["prefixes"].items()]
    return "\n".join(lines)


def stance_text(p: dict) -> str:
    extra = f" Note: {p['notes']}" if p.get("notes") else ""
    if p["type"] == "polar":
        return "affirms | denies | partial | hedged." + extra
    if p["type"] == "category":
        return "value = one of " + ", ".join(p["values"]) + "." + extra
    return "value = a number of people, or a range (low, high)." + extra


def propositions_text(topic: str) -> str:
    return "\n".join(f"- {p['id']}: {p['text']}  Stance: {stance_text(p)}"
                     for p in propositions(topic))


RULES = """Rules:
- Attribute every stance to the actor who stated it. Never state a contested proposition as a
  fact in your own voice, and never say who is right.
- When an actor's stance changes, keep the earlier stance with its date and note the change.
- Use the actor map. People appear only as office-holders, through their office or party;
  never name anyone else.
- Do not mention or compare the news outlets."""


def brief(topic: str) -> str:
    t = TOPICS[topic]
    return (f"Topic: {t.name}\n\nPropositions:\n{propositions_text(topic)}\n\n"
            f"Actor map:\n{actor_map_text()}\n\n{RULES}")
