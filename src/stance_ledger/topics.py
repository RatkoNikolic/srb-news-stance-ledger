"""The four contested topics: sentence-level cues and the publication window each one uses.

Cues are regular expressions over the lower-cased Latin text (surface forms, stems), so the
selection needs no lemmatiser and anyone can reproduce it from hydrated texts. A window is a
cue sentence with one sentence of context on each side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    cue: re.Pattern
    start: datetime
    end: datetime


def _rx(*alternatives: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{a})" for a in alternatives))


START, END = datetime(2024, 11, 1, tzinfo=UTC), datetime(2025, 5, 1, tzinfo=UTC)

TOPICS = {
    "T1": Topic(
        "T1", "Reconstruction documentation",
        _rx(r"dokumentacij\w*.{0,80}(objavlj|objavi|objavio|objavila|kompletn|potpun|nepotpun|"
            r"sva |svu |cel[ua] |nedostaj|skriva|nije objav|tajn)",
            r"(objavlj|objavi|kompletn|potpun|nepotpun|sva |svu |cel[ua] |nedostaj|skriva)"
            r".{0,80}dokumentacij",
            r"\b19[05] dokument", r"\b20[02] dokument", r"\b857 dokument"),
        START, END),
    "T2": Topic(
        "T2", "Students' demands",
        _rx(r"zahtev\w*.{0,80}(ispunj|ispuni|ispunio|ispunila|ispunjava|nisu ispunj|nije ispunj)",
            r"(ispunj|ispuni|ispunio|ispunila|ispunjava).{0,80}zahtev",
            r"(peti|novi|nove|novih|dodat\w*) zahtev",
            r"(raspis\w*|vanredn\w*|prevremen\w*) (parlamentarn\w* )?izbor\w*.{0,120}(student|plenum)",
            r"(student|plenum).{0,120}(raspis\w*|vanredn\w*|prevremen\w*) (parlamentarn\w* )?izbor",
            r"ekspertsk\w* vlad|prelazn\w* vlad"),
        START, END),
    "T3": Topic(
        "T3", "The sound on 15 March",
        _rx(r"zvučn\w* (top|topa|topom|topov|oružj|uređaj|talas)", r"\blrad\b",
            r"sonič\w*", r"(anti|protiv)-?dron\w* (puš|oružj|sistem|uređaj)",
            r"(nepoznat\w*|jak\w*|čudn\w*|zastrašujuć\w*) zvuk"),
        datetime(2025, 3, 15, tzinfo=UTC), END),
    "T4": Topic(
        "T4", "Crowd sizes, 15 March and 12 April",
        _rx(r"arhiv\w* javnih skupova",
            r"\b\d{2,3}(\.\d{3})?( |\.)?(hiljad\w*|000)\b.{0,80}"
            r"(ljudi|građan|okupil|prisustv|demonstrant|učesnik|na skupu|na protestu)",
            r"(okupil\w*|prisustv\w*|bilo je).{0,60}\b\d{2,3}(\.\d{3})?( |\.)?(hiljad\w*|000)\b",
            r"(milion|pola miliona) (ljudi|građan)",
            r"\bmup\w*.{0,60}(procen|broj).{0,40}(ljudi|građan|okupljen)"),
        datetime(2025, 3, 14, tzinfo=UTC), END),
}

# T4 counts only around its two events
T4_DAYS = [(datetime(2025, 3, 14, tzinfo=UTC), datetime(2025, 3, 26, tzinfo=UTC)),
           (datetime(2025, 4, 11, tzinfo=UTC), datetime(2025, 4, 23, tzinfo=UTC))]

LIVE_BLOG = re.compile(r"uživo|minut po minut|\bblog\b|\blive\b", re.IGNORECASE)


def in_window(topic: str, published: datetime) -> bool:
    t = TOPICS[topic]
    if not (t.start <= published < t.end):
        return False
    if topic == "T4":
        return any(a <= published < b for a, b in T4_DAYS)
    return True
