"""The shared input: one bundle per topic per 2-day step.

Every memory arm (both rolling summaries and the stance ledger) receives exactly the same
bundles, and the RAG arm searches the same window of time. A step k covers knowledge times in
(STEP0 + 2(k-1) days, STEP0 + 2k days]. Within a step: wire copies (identical normalised text)
already seen are skipped; at most 5 windows per outlet and 40 per topic, taking windows with
a reporting cue first (stances are attributed statements), then a stable hash order.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from stance_ledger.config import DATA, LOCAL

STEP0 = datetime(2024, 11, 1, tzinfo=UTC)
STEP = timedelta(days=2)
N_STEPS = 91                       # 1 Nov 2024 -> 1 May 2025
PER_OUTLET, PER_TOPIC = 5, 40

WINDOWS_ALL = LOCAL / "windows_all.parquet"
BUNDLES = LOCAL / "bundles.parquet"          # window text: local only
BUNDLE_INDEX = DATA / "bundle_index.parquet"  # ids, hashes, offsets: shipped

REPORTING = re.compile(
    r"\b(rekao|rekla|izjavi\w*|saopšt\w*|navodi|naveo|navela|tvrdi|tvrdio|tvrdila|kaže|"
    r"istak\w*|ocen\w*|poruči\w*|prema rečima|demantova\w*|odbaci\w*|potvrdi\w*|"
    r"objavi\w*|procen\w*)\b", re.IGNORECASE)


def step_end(k: int) -> datetime:
    return STEP0 + k * STEP


def step_of(t: datetime) -> int:
    """The last step whose end is at or before t."""
    return int((t - STEP0) / STEP)


def _rank(w: dict) -> tuple:
    h = hashlib.sha256(w["window_id"].encode()).hexdigest()
    return (0 if REPORTING.search(w["text"]) else 1, h)


def build() -> dict:
    rows = duckdb.sql(f"select * from '{WINDOWS_ALL}' order by known_at").to_arrow_table()
    rows = rows.to_pylist()
    seen: set[tuple[str, str]] = set()
    by_step: dict[tuple[str, int], list[dict]] = {}
    for w in rows:
        k = int((w["known_at"] - STEP0) / STEP) + 1   # the step that first sees it
        if 1 <= k <= N_STEPS:
            by_step.setdefault((w["topic"], k), []).append(w)
    out = []
    for (topic, k), ws in sorted(by_step.items()):
        picked, per_outlet = [], {}
        for w in sorted(ws, key=_rank):
            key = (topic, w["dup_key"])
            if key in seen or per_outlet.get(w["outlet_id"], 0) >= PER_OUTLET:
                continue
            seen.add(key)
            per_outlet[w["outlet_id"]] = per_outlet.get(w["outlet_id"], 0) + 1
            picked.append({**w, "step": k})
            if len(picked) >= PER_TOPIC:
                break
        out += sorted(picked, key=lambda w: w["known_at"])
    pq.write_table(pa.Table.from_pylist(out), BUNDLES)
    shipped = [{k: w[k] for k in ("window_id", "event_id", "topic", "step", "url",
                                  "published_at", "known_at", "live_blog", "start", "end",
                                  "window_sha256")} for w in out]
    pq.write_table(pa.Table.from_pylist(shipped), BUNDLE_INDEX)
    c = duckdb.connect()
    return dict(c.sql(f"select topic, count(*) from '{BUNDLES}' group by 1 order by 1").fetchall())


_ALL: dict[tuple[str, int], list[dict]] = {}


def bundle(topic: str, k: int) -> list[dict]:
    """Thread-safe: the bundles are read once into memory."""
    if not _ALL:
        rows = duckdb.connect().sql(f"select * from '{BUNDLES}' order by known_at")
        for w in rows.to_arrow_table().to_pylist():
            _ALL.setdefault((w["topic"], w["step"]), []).append(w)
    return _ALL.get((topic, k), [])
