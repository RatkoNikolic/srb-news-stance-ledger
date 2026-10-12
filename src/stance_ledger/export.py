"""Data for the static viewer (docs/data/viewer.json): the gold timelines, the
model-extracted ledger records (labelled unverified, with the measured error rates), the
attribution-survival series, and each arm's memory at a few example dates. No article text:
paraphrases are the models' English; links point to the articles. In the record list, text a
model wrote after the paraphrase sentence (JSON or tag fragments, 40 of 2,913 records) is cut for
display; the records file and the memories keep it, as the agent read it."""

from __future__ import annotations

import json
import re

from stance_ledger import ledger, summary
from stance_ledger.answer import gold
from stance_ledger.brief import propositions, registry
from stance_ledger.bundles import step_of
from stance_ledger.config import DATASET, DATASET_DOI, DATASET_VERSION, ROOT, RUNS
from stance_ledger.extract import scrub

OUT = ROOT / "docs" / "data" / "viewer.json"
_SPILL = re.compile(r"\s*[\]{}<`].*$", re.DOTALL)


def clean(paraphrase: str) -> str:
    """The paraphrase sentence without what the model wrote after it."""
    return _SPILL.sub("", paraphrase).rstrip(" ,") or paraphrase


def run(example_dates: list[str]) -> dict:
    from datetime import UTC, datetime
    recs = ledger.load()
    names = {a["id"]: a["name"] for a in registry()[1]["fixed"]}
    data = {
        "dataset": {"name": DATASET, "version": DATASET_VERSION, "doi": DATASET_DOI},
        "propositions": propositions(),
        "actors": names,
        "gold": [{"gid": g["gid"], "proposition": g["proposition"], "actor": g["actor"],
                  "stance": g["stance"], "value": g.get("value"),
                  "date": g["t"].date().isoformat(), "paraphrase": g["paraphrase_en"],
                  "evidence": [e["url"] for e in g["evidence"]],
                  "change_of": g.get("stance_change_of")} for g in gold()],
        "ledger": [{"proposition": r["proposition"], "actor": ledger.actor_key(r["actor"],
                                                                               r["known_at"]),
                    "stance": ledger.stance_value(r), "date": r["known_at"].date().isoformat(),
                    "paraphrase": clean(r["paraphrase_en"]), "url": r["url"]} for r in recs],
        "memories": {},
    }
    for d in example_dates:
        k = step_of(datetime.fromisoformat(d).replace(hour=23, minute=59, tzinfo=UTC))
        data["memories"][d] = {t: {
            "summary_unbriefed": scrub(summary.memory_at(t, "unbriefed", k)),
            "summary_briefed": scrub(summary.memory_at(t, "briefed", k)),
            "ledger": ledger.render(recs, t, k)} for t in ("T1", "T2", "T3", "T4")}
    rep = RUNS / "report.json"
    if rep.exists():
        r = json.loads(rep.read_text())
        data["survival"] = r.get("survival")
        data["scores"] = r.get("scores")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False))
    return {"gold": len(data["gold"]), "ledger": len(data["ledger"])}
