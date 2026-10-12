"""Model calls with a cost ledger and a hard budget stop.

Every call appends a row to runs/costs.jsonl (stage, model, tokens, batch, USD). Before any
call the ledger's total is checked against BUDGET_USD; a batch is estimated and refused up front
if it would cross the cap. Anthropic Messages API (sync) and Message Batches (50% price).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from stance_ledger.config import BUDGET_USD, PRICES, RUNS, load_env

COSTS = RUNS / "costs.jsonl"
_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def spent() -> float:
    if not COSTS.exists():
        return 0.0
    return sum(json.loads(x)["usd"] for x in COSTS.read_text().splitlines() if x.strip())


def guard(estimate: float = 0.0) -> None:
    if spent() + estimate > BUDGET_USD:
        raise BudgetExceeded(f"spent ${spent():.2f} + estimate ${estimate:.2f} > cap ${BUDGET_USD}")


def usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0,
        batch: bool = False) -> float:
    pin, pout = PRICES[model]
    cost = (inp * pin + cache_read * pin * 0.10 + cache_write * pin * 1.25 + out * pout) / 1e6
    return cost * (0.5 if batch else 1.0)


def record(stage: str, model: str, inp: int, out: int, cache_read: int = 0,
           cache_write: int = 0, batch: bool = False, n: int = 1) -> float:
    cost = usd(model, inp, out, cache_read, cache_write, batch)
    row = {"ts": datetime.now(UTC).isoformat(), "stage": stage, "model": model, "calls": n,
           "input": inp, "output": out, "cache_read": cache_read, "cache_write": cache_write,
           "batch": batch, "usd": round(cost, 6)}
    with _lock:
        COSTS.parent.mkdir(parents=True, exist_ok=True)
        with COSTS.open("a") as f:
            f.write(json.dumps(row) + "\n")
    return cost


# ---------------------------------------------------------------- Anthropic

def client() -> anthropic.Anthropic:
    load_env()
    return anthropic.Anthropic(max_retries=6)


def params(model: str, system: str, user: str, schema: dict | None = None,
           max_tokens: int = 4000, effort: str | None = None) -> dict:
    """Haiku and Sonnet run without extended thinking (high-volume, structured steps); Opus
    always thinks, and its depth is set by `effort`."""
    p = {"model": model, "max_tokens": max_tokens,
         "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
         "messages": [{"role": "user", "content": user}]}
    if "sonnet" in model:
        p["thinking"] = {"type": "between_tools"}
    elif "haiku" in model:
        p["thinking"] = {"type": "disabled"}
    oc = {}
    if schema:
        oc["format"] = {"type": "json_schema", "schema": schema}
    if effort:
        oc["effort"] = effort
    if oc:
        p["output_config"] = oc
    return p


def text_of(message) -> str:
    return "".join(b.text for b in message.content if b.type == "text")


def call(stage: str, p: dict) -> str:
    guard()
    m = client().messages.create(**p)
    u = m.usage
    record(stage, p["model"], u.input_tokens, u.output_tokens,
           u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0)
    return text_of(m)


def batch(stage: str, requests: dict[str, dict], state: Path, estimate: float,
          poll: int = 60) -> dict[str, str]:
    """Run a Message Batch (resumable: the batch id is kept in `state`). Returns id -> text;
    errored requests are left out and listed in the state file."""
    c = client()
    st = json.loads(state.read_text()) if state.exists() else {}
    if "batch_id" not in st:
        guard(estimate)
        b = c.messages.batches.create(requests=[{"custom_id": k, "params": v}
                                                 for k, v in requests.items()])
        st = {"batch_id": b.id, "stage": stage, "n": len(requests), "estimate": estimate}
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(st))
    while True:
        b = c.messages.batches.retrieve(st["batch_id"])
        if b.processing_status == "ended":
            break
        time.sleep(poll)
    out, errors, tok = {}, [], [0, 0, 0, 0]
    model = next(iter(requests.values()))["model"] if requests else ""
    for r in c.messages.batches.results(st["batch_id"]):
        if r.result.type == "succeeded":
            m = r.result.message
            out[r.custom_id] = text_of(m)
            u = m.usage
            tok[0] += u.input_tokens
            tok[1] += u.output_tokens
            tok[2] += u.cache_read_input_tokens or 0
            tok[3] += u.cache_creation_input_tokens or 0
            model = m.model if m.model in PRICES else model
        else:
            errors.append(r.custom_id)
    if not st.get("recorded"):
        record(stage, model, tok[0], tok[1], tok[2], tok[3], batch=True, n=len(out))
        st["recorded"] = True
    st["errors"] = errors
    state.write_text(json.dumps(st))
    return out
