"""Numbers for the results note (runs/report.json) and quick matplotlib checks
(docs/figures/quick/). The published figures are drawn by scripts/article_figures.py."""

from __future__ import annotations

import json
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from stance_ledger.answer import gold
from stance_ledger.bundles import step_end
from stance_ledger.config import ROOT, RUNS

FIG = ROOT / "docs" / "figures"
ARM_LABEL = {"summary_unbriefed": "Rolling summary", "summary_briefed": "Rolling summary + brief",
             "ledger": "Stance ledger", "ledger_corroborated": "Stance ledger, corroborated",
             "rag": "Search (RAG), no memory",
             "closed_book": "Closed book"}
COLOR = {"summary_unbriefed": "#c0504d", "summary_briefed": "#e3a33b", "ledger": "#2f6db3",
         "ledger_corroborated": "#1d4f8a",
         "rag": "#6b8e4e", "closed_book": "#888888"}


def survival_curve() -> dict:
    rows = json.loads((RUNS / "judge" / "survival.json").read_text())
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in rows:
        for lab in r["labels"].values():
            agg[r["arm"]][r["step"]][lab] += 1
    fig, ax = plt.subplots(figsize=(8, 4.5))
    out = {}
    for arm, by_step in agg.items():
        steps = sorted(by_step)
        share = [by_step[k]["attributed"] / max(1, sum(by_step[k].values())) for k in steps]
        out[arm] = {f"{step_end(k):%Y-%m-%d}": dict(by_step[k]) for k in steps}
        ax.plot([step_end(k) for k in steps], share, marker="o", color=COLOR[arm],
                label=ARM_LABEL[arm])
    ax.set_ylim(0, 1)
    ax.set_ylabel("stances kept with who said them")
    ax.set_title("How much of 'who said what' survives in the agent's memory")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.autofmt_xdate()
    (FIG / "quick").mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / "quick" / "survival.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def survival_final() -> dict:
    """Label shares at the last snapshot of each topic, per arm."""
    rows = json.loads((RUNS / "judge" / "survival.json").read_text())
    last = {}
    for r in rows:
        key = (r["arm"], r["topic"])
        if key not in last or r["step"] > last[key]["step"]:
            last[key] = r
    agg = defaultdict(lambda: defaultdict(int))
    for (arm, _), r in last.items():
        for lab in r["labels"].values():
            agg[arm][lab] += 1
    fig, ax = plt.subplots(figsize=(8, 3.2))
    labs = ["attributed", "stated_as_fact", "misattributed", "lost"]
    cols = ["#2f6db3", "#e3a33b", "#c0504d", "#cccccc"]
    arms = [a for a in ARM_LABEL if a in agg]
    for i, arm in enumerate(arms):
        tot, left = sum(agg[arm].values()), 0
        for lab, col in zip(labs, cols):
            v = agg[arm][lab] / max(1, tot)
            ax.barh(i, v, left=left, color=col, label=lab if i == 0 else None)
            left += v
    ax.set_yticks(range(len(arms)), [ARM_LABEL[a] for a in arms])
    ax.set_xlim(0, 1)
    ax.legend(ncol=4, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(FIG / "quick" / "survival_final.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return {a: dict(v) for a, v in agg.items()}


def crowd_chart() -> None:
    """T4 from the gold: each actor's latest figure for both events (opening image)."""
    from matplotlib.ticker import FuncFormatter

    from stance_ledger.ledger import actor_name
    gs = [g for g in gold() if g["proposition"] in ("P8", "P9") and isinstance(g.get("value"), dict)]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for ax, pid, title in ((axes[0], "P8", "Protest in Belgrade, 15 March 2025"),
                           (axes[1], "P9", "Rally 'Ne damo Srbiju' in Belgrade, 12 April 2025")):
        latest = {}
        for g in sorted((g for g in gs if g["proposition"] == pid), key=lambda g: g["t"]):
            v = g["value"]
            if v.get("low") or v.get("high"):
                latest[g["actor"]] = g
        items = sorted(latest.values(), key=lambda g: g["value"].get("high") or g["value"]["low"])
        for i, g in enumerate(items):
            lo = g["value"].get("low") or g["value"].get("high")
            hi = g["value"].get("high") or lo
            if hi > lo:
                ax.plot([lo / 1000, hi / 1000], [i, i], color="#2f6db3", lw=7,
                        solid_capstyle="round")
            else:
                ax.plot([lo / 1000], [i], "o", color="#2f6db3", ms=8)
        names = [actor_name(g["actor"]).split(" (")[0] for g in items]
        ax.set_yticks(range(len(items)), names, fontsize=8)
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}k"))
        ax.xaxis.set_minor_formatter(FuncFormatter(lambda x, _: ""))
        ax.set_xlabel("attendance as stated by each actor (log scale)", fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="x", color="#eeeeee")
    fig.suptitle("One crowd, many numbers: every figure is someone's claim", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "crowds.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


STANCE_COLOR = {"affirms": "#2f6db3", "denies": "#c0504d", "partial": "#e3a33b",
                "hedged": "#8a7cc2"}


def stance_timeline(pid: str, title: str, labels: dict, start: str, end: str,
                    fname: str, max_actors: int = 14) -> None:
    """One row per actor, one dot per stated stance (from the gold), a line joining
    an actor's stances; the actor's changes are visible as a change of colour along the row."""
    from datetime import datetime, timedelta

    import matplotlib.dates as mdates

    from stance_ledger.ledger import actor_name
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    gs = sorted((g for g in gold() if g["proposition"] == pid
                 and a <= g["t"].replace(tzinfo=None) <= b), key=lambda g: g["t"])
    rows: dict[str, list] = {}
    for g in gs:
        rows.setdefault(g["actor"], []).append(g)
    order = sorted(rows, key=lambda k: (-len(rows[k]), rows[k][0]["t"]))[:max_actors]
    order = sorted(order, key=lambda k: rows[k][0]["t"], reverse=True)
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(order) + 1.6))
    for i, actor in enumerate(order):
        pts = rows[actor]
        xs = [g["t"].replace(tzinfo=None) for g in pts]
        ax.plot(xs + [b], [i] * (len(xs) + 1), color="#dddddd", lw=1.5, zorder=1)
        for g, x in zip(pts, xs):
            ax.scatter([x], [i], s=110, color=STANCE_COLOR.get(g["stance"], "#888"),
                       zorder=3, edgecolor="white", linewidth=0.8)
    ax.set_yticks(range(len(order)),
                  [actor_name(k).split(" (")[0].replace("academic:", "") for k in order],
                  fontsize=8.5)
    ax.set_xlim(a - timedelta(days=0.5), b)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    handles = [plt.Line2D([], [], marker="o", ls="", color=STANCE_COLOR[k], ms=9, label=v)
               for k, v in labels.items()]
    ax.legend(handles=handles, ncol=len(handles), frameon=False, fontsize=8.5,
              loc="lower center", bbox_to_anchor=(0.5, 1.0))
    ax.set_title(title, fontsize=11, pad=28)
    fig.savefig(FIG / fname, dpi=180, bbox_inches="tight")
    plt.close(fig)


def example_charts() -> None:
    crowd_chart()
    stance_timeline("P6", "\"Do state bodies have a sound device?\" Who said what, 15-25 March 2025",
                    {"affirms": "yes", "partial": "yes, with caveats", "denies": "no"},
                    "2025-03-15", "2025-03-25", "sound_device.png")
    stance_timeline("P2", "\"Have the students' demands been fulfilled?\" Who said what, Dec 2024 to Apr 2025",
                    {"affirms": "all fulfilled", "partial": "partly", "hedged": "hedged",
                     "denies": "not fulfilled"},
                    "2024-12-08", "2025-04-30", "demands.png")


def costs() -> dict:
    rows = [json.loads(x) for x in (RUNS / "costs.jsonl").read_text().splitlines() if x.strip()]
    by = defaultdict(float)
    for r in rows:
        by[r["stage"]] += r["usd"]
    return {k: round(v, 3) for k, v in sorted(by.items())}


def run() -> dict:
    rep = {"survival": survival_curve(), "survival_final": survival_final(),
           "scores": json.loads((RUNS / "scores_summary.json").read_text()), "costs": costs()}
    fact = RUNS / "judge" / "stated_as_fact.json"
    if fact.exists():
        v = json.loads(fact.read_text())
        agg = defaultdict(lambda: defaultdict(int))
        for k, verdict in v.items():
            agg[k.split("|")[0]][verdict] += 1
        rep["stated_as_fact"] = {a: dict(x) for a, x in agg.items()}
    (RUNS / "report.json").write_text(json.dumps(rep, indent=1))
    return rep
