"""Paths, models and prices. Every run manifest records the model ids used by role."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.environ.get("STANCE_LEDGER_ROOT", Path(__file__).resolve().parents[2]))
DATA = ROOT / "data"          # shipped: subset index, registry, gold, questions
LOCAL = ROOT / "local"        # never committed: article text and anything derived verbatim from it
RUNS = ROOT / "runs"          # shipped: model outputs, answers, scores, costs

DATASET = "canopy-collapse-news-2024-2025"
DATASET_VERSION = "1.1.0"
DATASET_DOI = "10.5281/zenodo.23261738"
WINDOW = (datetime(2024, 11, 1, tzinfo=UTC), datetime(2025, 5, 1, tzinfo=UTC))

MODELS = {
    "filter": "claude-haiku-5-5",     # drops windows with no stance (batch)
    "extract": "claude-sonnet-5-5",   # stance records (batch)
    "summary": "claude-sonnet-5-5",   # rolling summaries (sequential)
    "render": "claude-sonnet-5-5",    # ledger memory wording
    "reader": "claude-sonnet-5-5",    # answers questions from each arm's memory (batch)
    "judge": "claude-opus-5-5",       # the strongest model checks the others' memories (batch)
}

# $ per 1M tokens (input, output), standard API. Batch = 50%; cache read = 10% of input,
# cache write = 125%. Anthropic price table cached 2026-10-06.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
BUDGET_USD = 116.0   # the approved cap, EUR 100 (2026-10-12)


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
