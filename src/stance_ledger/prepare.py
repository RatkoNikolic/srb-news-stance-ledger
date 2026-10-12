"""Article texts for the subset, from either source:

- `from_documents`: the dataset's own build (the authors' path): `builds/documents/<extractor>/`
  of canopy-collapse-news, joined to the release's index and scope files;
- `from_hydrated`: the JSON lines written by `canopy-news hydrate --index data/subset_index.parquet`
  (anyone's path). Articles that came back `changed` are kept and flagged; `gone` and `failed`
  are reported and left out.

Both write local/articles.parquet (event_id, url, outlet_id, published_at, title, lead, body,
hydrate_outcome). That file holds article text and is never committed.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from stance_ledger.config import DATA, LOCAL

ARTICLES = LOCAL / "articles.parquet"
SUBSET = DATA / "subset_index.parquet"
COLS = "event_id, url, outlet_id, published_at, title, lead, body, hydrate_outcome"


def from_documents(documents: Path, index: Path, scope: Path, out: Path = ARTICLES) -> int:
    """All in-scope articles with text (the subset is selected from these by `select`)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect()
    c.sql(f"""
        copy (
          select d.event_id, i.url, i.outlet_id,
                 cast(i.published_at as timestamptz) as published_at,
                 d.title, d.lead, d.body, 'matched' as hydrate_outcome
          from read_parquet('{documents}/*.parquet') d
          join read_parquet('{index}') i using (event_id)
          join read_parquet('{scope}') s using (event_id)
          where s.in_scope and i.status = 'article' and d.error is null
        ) to '{out}' (format parquet)""")
    return c.sql(f"select count(*) from '{out}'").fetchone()[0]


def from_hydrated(texts: Path, subset: Path = SUBSET, out: Path = ARTICLES) -> dict:
    rows = []
    for f in sorted(texts.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("outcome") in ("matched", "changed"):
                rows.append({k: r.get(k) for k in ("event_id", "title", "lead", "body", "outcome")})
    out.parent.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect()
    tmp = LOCAL / "_hydrated.jsonl"
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    c.sql(f"""
        copy (
          select s.event_id, s.url, s.outlet_id, cast(s.published_at as timestamptz) as published_at,
                 h.title, h.lead, h.body, h.outcome as hydrate_outcome
          from read_parquet('{subset}') s join read_json_auto('{tmp}') h using (event_id)
        ) to '{out}' (format parquet)""")
    tmp.unlink()
    n = c.sql(f"select count(*) from read_parquet('{subset}')").fetchone()[0]
    got = c.sql(f"select hydrate_outcome, count(*) from '{out}' group by 1").fetchall()
    return {"subset": n, **dict(got), "missing": n - sum(v for _, v in got)}
