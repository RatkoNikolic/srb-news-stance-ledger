"""Deterministic scoring of the readers' structured answers against the gold timelines.

For a question on proposition P at step k, the gold as of then is every gold stance on P
first published before the step's end; an actor's current stance is its latest one. Per answer:

- recall: share of gold actors whose current stance the answer gives (same actor, same stance);
- stale: answer stances equal to that actor's earlier, replaced gold stance;
- ahead_of_gold: answer stances equal to a stance the gold dates later. For every arm with
  as-of input this cannot be leakage (input is filtered to the date); it means the corpus
  carried the stance before the gold's first date, i.e. the gold dates it late. Only for
  closed_book is it a true anachronism;
- changes detected: share of gold stance changes (both ends known by then) that the answer
  reports for that actor;
- unmatched: answer positions whose actor has no gold record (the gold is not exhaustive, so
  this is reported, not counted as an error).

Actors match exactly, or for prefixed ids (students:…, party:…) by name overlap.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from stance_ledger.answer import gold
from stance_ledger.bundles import step_end
from stance_ledger.config import RUNS
from stance_ledger.ledger import same

_W = re.compile(r"[a-zčćšžđ0-9]+")


def norm_stance(s) -> str:
    if isinstance(s, dict):
        lo, hi = s.get("low"), s.get("high")
        return f"{lo}-{hi}" if lo and hi and lo != hi else str(lo or hi)
    s = str(s or "").strip().lower().replace(",", "").replace(" ", "")
    m = re.findall(r"\d+(?:\.\d+)?", s)
    if m and not re.search(r"[a-z]{3,}", s):
        return "-".join(m[:2])
    return s


def gold_stance(g: dict) -> str:
    return norm_stance(g["value"]) if g.get("value") else norm_stance(g["stance"])


def actor_match(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    if ":" in a and ":" in b and a.split(":")[0] == b.split(":")[0]:
        ta, tb = set(_W.findall(a.split(":", 1)[1])), set(_W.findall(b.split(":", 1)[1]))
        return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.5
    return False


def stance_match(a: str, b: str) -> bool:
    a, b = norm_stance(a), norm_stance(b)
    return a == b or (a[:1].isdigit() and b[:1].isdigit() and same(a, b))


def score_one(ans: dict, golds: list[dict], k: int) -> dict:
    t = step_end(k)
    by_actor = defaultdict(list)
    for g in sorted(golds, key=lambda g: g["t"]):
        by_actor[g["actor"]].append(g)
    known = {a: [g for g in gs if g["t"] <= t] for a, gs in by_actor.items()}
    known = {a: gs for a, gs in known.items() if gs}
    pos = ans.get("positions", [])
    hit, stale, anach, unmatched = 0, 0, 0, 0
    for p in pos:
        actor = next((a for a in by_actor if actor_match(p["actor"], a)), None)
        if actor is None:
            unmatched += 1
            continue
        hist = known.get(actor, [])
        later = [g for g in by_actor[actor] if g["t"] > t]
        if hist and stance_match(p["stance"], gold_stance(hist[-1])):
            hit += 1
        elif any(stance_match(p["stance"], gold_stance(g)) for g in hist[:-1]):
            stale += 1
        elif any(stance_match(p["stance"], gold_stance(g)) for g in later):
            anach += 1
    changes = [(a, gs[i - 1], gs[i]) for a, gs in known.items() for i in range(1, len(gs))
               if not stance_match(gold_stance(gs[i - 1]), gold_stance(gs[i]))]
    detected = 0
    for a, g0, g1 in changes:
        if any(actor_match(c["actor"], a) and stance_match(c["to_stance"], gold_stance(g1))
               for c in ans.get("changes", [])):
            detected += 1
    # reported changes for an actor the gold knows by then, with no gold change: false alarms
    changed = {a for a, _, _ in changes}
    false_changes = sum(
        1 for c in ans.get("changes", [])
        if (a := next((a for a in known if actor_match(c["actor"], a)), None))
        and a not in changed)
    return {"gold_actors": len(known), "recall_hits": hit, "positions": len(pos),
            "stale": stale, "anachronism": anach, "unmatched": unmatched,
            "gold_changes": len(changes), "changes_detected": detected,
            "changes_reported": len(ans.get("changes", [])), "false_changes": false_changes}


def run() -> dict:
    answers = json.loads((RUNS / "answers" / "answers.json").read_text())
    golds = gold()
    by_prop = defaultdict(list)
    for g in golds:
        by_prop[g["proposition"]].append(g)
    rows = []
    for key, ans in answers.items():
        arm, pid, k = key.split("|")
        rows.append({"arm": arm, "proposition": pid, "step": int(k),
                     **score_one(ans, by_prop[pid], int(k))})
    (RUNS / "scores.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for f in ("gold_actors", "recall_hits", "positions", "stale", "anachronism",
                  "unmatched", "gold_changes", "changes_detected", "changes_reported",
                  "false_changes"):
            agg[r["arm"]][f] += r[f]
    out = {}
    for arm, a in agg.items():
        out[arm] = {"recall": a["recall_hits"] / max(1, a["gold_actors"]),
                    "stale_per_100_positions": 100 * a["stale"] / max(1, a["positions"]),
                    "ahead_of_gold_per_100_positions": 100 * a["anachronism"] / max(1, a["positions"]),
                    "change_detection": a["changes_detected"] / max(1, a["gold_changes"]),
                    "unmatched_share": a["unmatched"] / max(1, a["positions"]),
                    "changes_reported": a["changes_reported"],
                    "false_changes": a["false_changes"],
                    "gold_changes": a["gold_changes"],
                    "n_questions": sum(1 for r in rows if r["arm"] == arm)}
    (RUNS / "scores_summary.json").write_text(json.dumps(out, indent=1))
    return out


def bootstrap(n: int = 2000, seed: int = 7) -> dict:
    """95% intervals for recall and change detection per arm, and for the ledger minus each
    other arm, resampling questions (proposition x step) with replacement (paired)."""
    import random
    rows = [json.loads(x) for x in (RUNS / "scores.jsonl").read_text().splitlines()]
    qs = sorted({(r["proposition"], r["step"]) for r in rows})
    by = {(r["arm"], r["proposition"], r["step"]): r for r in rows}
    arms = sorted({r["arm"] for r in rows})
    rnd = random.Random(seed)

    def stat(sample, arm, num, den):
        a = sum(by[(arm, *q)][num] for q in sample)
        b = sum(by[(arm, *q)][den] for q in sample)
        return a / b if b else 0.0

    out = {}
    for metric, num, den in (("recall", "recall_hits", "gold_actors"),
                             ("change_detection", "changes_detected", "gold_changes")):
        draws = defaultdict(list)
        for _ in range(n):
            s = [rnd.choice(qs) for _ in qs]
            vals = {arm: stat(s, arm, num, den) for arm in arms}
            for arm in arms:
                draws[arm].append(vals[arm])
                if arm != "ledger":
                    draws[f"ledger_minus_{arm}"].append(vals["ledger"] - vals[arm])
        out[metric] = {k: [round(sorted(v)[int(0.025 * n)], 3), round(sorted(v)[int(0.975 * n)], 3)]
                       for k, v in draws.items()}
    (RUNS / "scores_ci.json").write_text(json.dumps(out, indent=1))
    return out
