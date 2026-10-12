"""stance-ledger: command line.

  stance-ledger prepare --hydrated texts/            # after canopy-news hydrate (anyone)
  stance-ledger prepare --documents D --index I --scope S   # from the dataset build (authors)
  stance-ledger windows | bundles                    # selection (free, deterministic)
  stance-ledger extract                              # ledger: filter + extract ($, batch)
  stance-ledger summaries                            # rolling summaries, both variants ($)
  stance-ledger answer | judge | score | report      # evaluation ($ for answer and judge)
  stance-ledger show --topic T3 --as-of 2025-03-20   # print the ledger memory (free)
  stance-ledger ask "question" --as-of 2025-03-20 --arm ledger   # your own question ($)
  stance-ledger cost                                 # spend so far, from runs/costs.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="stance-ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare")
    pr.add_argument("--hydrated", type=Path)
    pr.add_argument("--documents", type=Path)
    pr.add_argument("--index", type=Path)
    pr.add_argument("--scope", type=Path)
    for c in ("windows", "bundles", "extract", "summaries", "answer", "judge", "score",
              "report", "cost"):
        sub.add_parser(c)
    sh = sub.add_parser("show")
    sh.add_argument("--topic", required=True)
    sh.add_argument("--as-of", required=True)
    ak = sub.add_parser("ask")
    ak.add_argument("question")
    ak.add_argument("--as-of", required=True)
    ak.add_argument("--arm", default="ledger",
                    choices=["ledger", "summary_briefed", "summary_unbriefed", "rag"])
    ak.add_argument("--topic", default=None)
    a = ap.parse_args()

    if a.cmd == "prepare":
        from stance_ledger import prepare
        if a.hydrated:
            print(prepare.from_hydrated(a.hydrated))
        else:
            print(prepare.from_documents(a.documents, a.index, a.scope))
    elif a.cmd == "windows":
        import duckdb
        import pyarrow as pa
        import pyarrow.parquet as pq

        from stance_ledger.prepare import ARTICLES
        from stance_ledger.windows import windows_for
        rows = duckdb.sql(f"select * from '{ARTICLES}'").to_arrow_table().to_pylist()
        ws = [w for r in rows for w in windows_for(r)]
        pq.write_table(pa.Table.from_pylist(ws), ARTICLES.parent / "windows_all.parquet")
        print(len(ws), "windows")
    elif a.cmd == "bundles":
        from stance_ledger.bundles import build
        print(build())
    elif a.cmd == "extract":
        from stance_ledger import extract
        extract.run_filter()
        print(len(extract.run_extract()), "records")
    elif a.cmd == "summaries":
        from stance_ledger import summary
        print(summary.run())
    elif a.cmd == "answer":
        from stance_ledger import answer
        print(answer.run())
    elif a.cmd == "judge":
        from stance_ledger import judge
        judge.survival()
        judge.stated_as_fact()
    elif a.cmd == "score":
        from stance_ledger import score
        print(json.dumps(score.run(), indent=1))
    elif a.cmd == "report":
        from stance_ledger import report
        report.run()
    elif a.cmd == "cost":
        from stance_ledger.config import BUDGET_USD
        from stance_ledger.llm import spent
        print(f"spent ${spent():.2f} of ${BUDGET_USD:.0f}")
    elif a.cmd in ("show", "ask"):
        from stance_ledger import ledger
        from stance_ledger.bundles import step_of
        t = datetime.fromisoformat(a.as_of).replace(hour=23, minute=59, tzinfo=UTC)
        k = step_of(t)
        if a.cmd == "show":
            print(ledger.render(ledger.load(), a.topic, k))
            return
        from stance_ledger import ask
        print(ask.ask(a.question, k, a.arm, a.topic))


if __name__ == "__main__":
    main()
