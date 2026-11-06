"""The figures in docs/figures/, drawn as HTML/SVG and rendered to PNG (2x) in a headless browser
(typography: Bricolage Grotesque + Instrument Sans from Google Fonts).

    uv run python scripts/article_figures.py [--chromium PATH]

Needs Playwright and network access for the fonts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stance_ledger.answer import gold
from stance_ledger.bundles import step_end
from stance_ledger.ledger import actor_name

FIG = ROOT / "docs" / "figures"

T = {  # design tokens
    "paper": "#F6F7F5", "ink": "#182230", "muted": "#5C6675", "faint": "#8A939F",
    "rule": "#DCE0E3", "track": "#E8EBED",
    "yes": "#2a78d6", "no": "#e34948", "partly": "#eda100", "hedged": "#6250d6",
    "ledger": "#182230", "briefed": "#7C8899", "plain": "#B9C1CB",
}
ARM_COLOR = {"ledger": T["ledger"], "summary_briefed": T["briefed"],
             "summary_unbriefed": T["plain"]}
STANCE = {"affirms": "yes", "denies": "no", "partial": "partly", "hedged": "hedged"}
FONTS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800"
         "&family=Instrument+Sans:wght@400..700&display=block")
CSS = f"""
@import url('{FONTS}');
* {{ box-sizing: border-box; margin: 0; padding: 0 }}
body {{ background: {T['paper']}; color: {T['ink']}; font-family: 'Instrument Sans', sans-serif;
       -webkit-font-smoothing: antialiased }}
.fig {{ padding: 56px 64px 44px; background: {T['paper']} }}
.fig h1 {{ font-family: 'Bricolage Grotesque', sans-serif; font-weight: 700; font-size: 40px;
          line-height: 1.12; letter-spacing: -0.01em; max-width: 30ch }}
.fig .sub {{ font-size: 21px; color: {T['muted']}; margin-top: 12px; max-width: 64ch;
            line-height: 1.4 }}
.fig .src {{ font-size: 16px; color: {T['faint']}; margin-top: 18px }}
svg text {{ font-family: 'Instrument Sans', sans-serif; font-variant-numeric: tabular-nums }}
.legend {{ display: flex; gap: 28px; margin-top: 22px; font-size: 19px; color: {T['muted']} }}
.legend span {{ display: inline-flex; align-items: center; gap: 9px }}
"""


def shape(stance: str, x: float, y: float, r: float = 9) -> str:
    """Each stance has its own colour and shape, so it never relies on colour alone."""
    c = T[STANCE.get(stance, "hedged")]
    ring = f'stroke="{T["paper"]}" stroke-width="2.5"'
    if stance == "denies_narrow":
        return (f'<rect x="{x-r+2.5:.1f}" y="{y-r+2.5:.1f}" width="{2*r-5}" height="{2*r-5}" rx="2" '
                f'fill="{T["paper"]}" stroke="{T["no"]}" stroke-width="3"/>')
    if stance == "denies":
        return f'<rect x="{x-r+1:.1f}" y="{y-r+1:.1f}" width="{2*r-2}" height="{2*r-2}" rx="2" fill="{c}" {ring}/>'
    if stance == "partial":
        return (f'<path d="M{x:.1f},{y-r-1:.1f} L{x+r+1:.1f},{y:.1f} L{x:.1f},{y+r+1:.1f} '
                f'L{x-r-1:.1f},{y:.1f} Z" fill="{c}" {ring}/>')
    if stance == "hedged":
        return (f'<path d="M{x:.1f},{y-r:.1f} L{x+r:.1f},{y+r*0.8:.1f} L{x-r:.1f},{y+r*0.8:.1f} Z" '
                f'fill="{c}" {ring}/>')
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}" {ring}/>'


def legend_html(items: list[tuple[str, str]]) -> str:
    out = []
    for stance, label in items:
        out.append(f'<span><svg width="22" height="22">{shape(stance, 11, 11, 8)}</svg>'
                   f'{escape(label)}</span>')
    return f'<div class="legend">{"".join(out)}</div>'


def short_name(actor: str) -> str:
    n = actor_name(actor).split(" (")[0]
    for a, b in (("Prime Minister Miloš Vučević", "Prime Minister"),
                 ("Speaker of the National Assembly", "Speaker of parliament"),
                 ("Ministry of Defence and the Army", "Ministry of Defence"),
                 ("Security Information Agency", "Security agency (BIA)"),
                 ("University of Belgrade expert working group", "University of Belgrade experts"),
                 ("Deans of University of Novi Sad faculties", "Novi Sad faculty deans"),
                 ("Archive of Public Gatherings", "Archive of Public Gatherings"),
                 ("Government of Serbia", "Government"), ("FDU Belgrade", "Drama faculty students"),
                 ("Faculty of Dramatic Arts Belgrade", "Drama faculty students"),
                 ("FTN Novi Sad", "Novi Sad technical students"),
                 ("Faculty of Civil Engineering Belgrade", "Civil Engineering students"),
                 ("Students in blockade", "Students in blockade")):
        if n == a:
            return b
    return n


def fmt_k(v: float) -> str:
    return f"{v/1e6:g}M" if v >= 1e6 else f"{v/1e3:g}k"


def fmt_n(v: int) -> str:
    return f"{v:,}"


# ------------------------------------------------------------------------- display rules

LABEL = {  # figures the speaker relayed or cited rather than produced
    "T4-03": "BIA, via the President",
    "T4-04": "Military security, via President",
    "T4-07": "Students (interviewed)",
    "T4-15": "Police, via the President",
    "T4-20": "Speaker, citing Interior Ministry",
    "T4-21": "PM, citing Interior Ministry",
}
NARROW_DENIAL = {"T3-28", "T3-29", "T3-30", "T3-31"}  # denied only for itself or for named models


# Statements found in the corpus after the answer key was frozen. They are drawn on the charts but
# are not in data/gold, so every benchmark number stays computed on the published key.
CHART_EXTRA = [
    {"gid": "X-01", "proposition": "P6", "actor": "ministry_interior", "stance": "denies",
     "first_published_at": "2025-03-18T09:31:59Z",
     "evidence": ["https://www.pink.rs/politika/677964/dacic-srbija-nema-zvucni-top-samo-jaci-megafon-a-ni-to-ne-koristi",
                  "https://www.danas.rs/vesti/drustvo/ima-topa-nema-topa-u-magacinu-je-ustvari-pored-skupstine-dacic-danima-ne-moze-da-se-dogovori-sam-sa-sobom/"],
     "paraphrase_en": "On TV Prva the minister said Serbia and its police have no sound cannon, only a "
                      "sound amplifier like a stronger megaphone, and that even that is not used."},
]


def chart_gold() -> list[dict]:
    """The answer key plus CHART_EXTRA, with narrow denials drawn as their own marker."""
    extra = [{**g, "t": datetime.fromisoformat(g["first_published_at"])} for g in CHART_EXTRA]
    return [{**g, "stance": "denies_narrow"} if g["gid"] in NARROW_DENIAL and g["stance"] == "denies"
            else g for g in gold() + extra]


def row_label(actor: str, recs: list[dict]) -> str:
    for g in reversed(recs):
        if g["gid"] in LABEL:
            return LABEL[g["gid"]]
    return short_name(actor)


# ------------------------------------------------------------------------- crowd claims

def crowd_svg(pid: str, width: int, row_h: int = 48, fs: int = 19, left: int = 330) -> str:
    """Every figure each source gave: the latest filled, earlier ones hollow with their own label."""
    gs = [g for g in chart_gold() if g["proposition"] == pid and isinstance(g.get("value"), dict)
          and (g["value"].get("low") or g["value"].get("high"))]
    by: dict[str, list] = {}
    for g in sorted(gs, key=lambda g: g["t"]):
        by.setdefault(g["actor"], []).append(g)

    def hi_of(g):
        return g["value"].get("high") or g["value"]["low"]

    def lo_of(g):
        return g["value"].get("low") or g["value"]["high"]

    order = sorted(by, key=lambda a: hi_of(by[a][-1]), reverse=True)
    right = width - 40
    lo_v = min(lo_of(g) for gs_ in by.values() for g in gs_) * 0.72
    hi_v = 1_400_000

    def x(v):
        return left + (math.log10(v) - math.log10(lo_v)) / (math.log10(hi_v) - math.log10(lo_v)) * (right - left - 220)

    h = 44 + row_h * len(order) + 34
    parts = [f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}">']
    for tv in (20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000):
        if tv < lo_v:
            continue
        parts.append(f'<line x1="{x(tv):.1f}" x2="{x(tv):.1f}" y1="30" y2="{h-34}" stroke="{T["rule"]}" stroke-width="1"/>')
        parts.append(f'<text x="{x(tv):.1f}" y="{h-8}" font-size="{fs-3}" fill="{T["faint"]}" text-anchor="middle">{fmt_k(tv)}</text>')
    for i, actor in enumerate(order):
        y = 44 + i * row_h + row_h / 2
        parts.append(f'<text x="{left-24}" y="{y+6:.1f}" font-size="{fs}" fill="{T["ink"]}" text-anchor="end">{escape(row_label(actor, by[actor]))}</text>')
        parts.append(f'<line x1="{left-8}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{T["track"]}" stroke-width="1"/>')
        figs = by[actor]
        for j, g in enumerate(figs):
            lo, hi = lo_of(g), hi_of(g)
            latest = j == len(figs) - 1
            col = T["ink"] if latest else T["faint"]
            if hi > lo:
                dim = "" if latest else 'stroke-opacity="0.55"'
                parts.append(f'<line x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="10" stroke-linecap="round" {dim}/>')
                label = f"{fmt_n(lo)}–{fmt_n(hi)}"
            elif latest:
                parts.append(f'<circle cx="{x(lo):.1f}" cy="{y:.1f}" r="8" fill="{T["ink"]}" stroke="{T["paper"]}" stroke-width="2.5"/>')
                label = fmt_n(lo)
            else:
                parts.append(f'<circle cx="{x(lo):.1f}" cy="{y:.1f}" r="7" fill="{T["paper"]}" stroke="{T["faint"]}" stroke-width="2.5"/>')
                label = fmt_n(lo)
            if latest:
                xmax = max(x(hi_of(f)) for f in figs)
                if xmax > x(hi) + 5:   # an earlier figure sits to the right: label on the left
                    parts.append(f'<text x="{x(lo)-18:.1f}" y="{y+6:.1f}" font-size="{fs}" font-weight="600" fill="{T["ink"]}" text-anchor="end">{label}</text>')
                else:
                    parts.append(f'<text x="{x(hi)+18:.1f}" y="{y+6:.1f}" font-size="{fs}" font-weight="600" fill="{T["ink"]}">{label}</text>')
            else:
                parts.append(f'<text x="{x(hi)+4:.1f}" y="{y-14:.1f}" font-size="{fs-5}" fill="{T["muted"]}" text-anchor="end">earlier {label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def crowds_html() -> str:
    body = (f'<h1>One crowd, many numbers</h1>'
            f'<p class="sub">Attendance as stated by each source, at the protest of 15 March and '
            f'the rally of 12 April 2025. Every figure is a claim. Where a source revised its '
            f'figure, the earlier one is shown in grey.</p>'
            f'<h2 class="panel">Protest in Belgrade, 15 March 2025</h2>{crowd_svg("P8", 1072)}'
            f'<h2 class="panel">Rally "Ne damo Srbiju" in Belgrade, 12 April 2025</h2>{crowd_svg("P9", 1072)}'
            f'<p class="src">Horizontal scale is logarithmic. Not counted as estimates: a rhetorical "a million '
            f'people came under your window" (a Serbia Centre member, 23 March); for the rally, a '
            f'25,000 "internal police figure" cited by the SSP leader and an archive member\'s "no '
            f'more than 40,000 when the President began speaking". Source: statements in nine '
            f'Serbian outlets (canopy-collapse-news v1.1.0), the stance-ledger answer key.</p>')
    extra = (".panel { font-family: 'Bricolage Grotesque'; font-weight: 600; font-size: 24px; "
             "margin: 34px 0 4px }")
    return page(body, extra)


# ------------------------------------------------------------------------- stance timelines

def timeline_svg(pid: str, start: datetime, end: datetime, width: int, max_actors: int = 14,
                 row_h: int = 52, fs: int = 19, tick_days: int | None = None,
                 left: int = 360) -> str:
    gs = sorted((g for g in chart_gold() if g["proposition"] == pid and start <= g["t"] <= end),
                key=lambda g: g["t"])
    rows: dict[str, list] = {}
    for g in gs:
        rows.setdefault(g["actor"], []).append(g)
    order = sorted(rows, key=lambda k: (-len(rows[k]), rows[k][0]["t"]))[:max_actors]
    order = sorted(order, key=lambda k: rows[k][0]["t"])
    right = width - 50
    span = (end - start).total_seconds()

    def x(t):
        return left + (t - start).total_seconds() / span * (right - left)

    h = 30 + row_h * len(order) + 40
    p = [f'<svg width="{width}" height="{h}" viewBox="0 0 {width} {h}">']
    # time axis ticks
    t = start.replace(hour=0, minute=0, second=0)
    if tick_days is None:   # month starts
        ticks = []
        m = datetime(start.year, start.month, 1, tzinfo=UTC)
        while m <= end:
            if m >= start:
                ticks.append((m, f"{m:%b}" if m.month != 1 else f"{m:%b %Y}"))
            m = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1, tzinfo=UTC)
    else:
        ticks = []
        while t <= end:
            ticks.append((t, f"{t.day} {t:%b}"))
            t += timedelta(days=tick_days)
    for tt, lab in ticks:
        p.append(f'<line x1="{x(tt):.1f}" x2="{x(tt):.1f}" y1="14" y2="{h-38}" stroke="{T["rule"]}" stroke-width="1"/>')
        p.append(f'<text x="{x(tt):.1f}" y="{h-12}" font-size="{fs-3}" fill="{T["faint"]}" text-anchor="middle">{lab}</text>')
    for i, actor in enumerate(order):
        y = 30 + i * row_h + row_h / 2 + 6
        pts = rows[actor]
        p.append(f'<text x="{left-24}" y="{y+6:.1f}" font-size="{fs}" fill="{T["ink"]}" text-anchor="end">{escape(row_label(actor, rows[actor]))}</text>')
        p.append(f'<line x1="{x(pts[0]["t"]):.1f}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{T["rule"]}" stroke-width="2"/>')
        # points reported on the same day share one date label, centred under or over them
        groups: list[list[dict]] = []
        for g in pts:
            if groups and groups[-1][-1]["t"].date() == g["t"].date():
                groups[-1].append(g)
            else:
                groups.append([g])
        prev_x, below = -1e9, False
        for grp in groups:
            xs = [x(g["t"]) for g in grp]
            for g, gx in zip(grp, xs):
                p.append(shape(g["stance"], gx, y, 9))
            lx = sum(xs) / len(xs)
            below = (not below) if xs[0] - prev_x < 74 else False
            prev_x = xs[-1]
            ty = y + 30 if below else y - 16
            t0 = grp[0]["t"]
            p.append(f'<text x="{lx:.1f}" y="{ty:.1f}" font-size="{fs-4}" fill="{T["muted"]}" text-anchor="middle">{t0.day} {t0:%b}</text>')
    p.append("</svg>")
    return "".join(p)


def sound_html() -> str:
    body = ('<h1>"Do state bodies have a sound device?"</h1>'
            '<p class="sub">What each institution and party said in the ten days after the '
            'protest of 15 March 2025, with the date each statement was first reported.</p>'
            + legend_html([("affirms", "yes"), ("partial", "yes, with caveats"), ("denies", "no"),
                           ("denies_narrow", "no, but only for itself or for named models")])
            + timeline_svg("P6", datetime(2025, 3, 15, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC),
                           1072, tick_days=2)
            + '<p class="src">Narrow denials: the Army and BIA spoke only for themselves; the '
              'Interior Ministry first denied only named models (Vortex, LRAD-1000Xi); the President '
              'first said only that the Army had no such device and no state body a "Vortex". The '
              'next morning the interior minister said Serbia has no sound cannon at all, only a '
              '"stronger megaphone"; by 19 March he showed the ministry\'s LRAD units, which he said '
              'were for warnings and were not used on 15 March. Source: stance-ledger answer key, plus '
              'the minister\'s 18 March statement (Pink, Danas), found in the corpus after the key was '
              'frozen.</p>')
    return page(body)


def demands_html() -> str:
    body = ('<h1>"Have the students\' demands been fulfilled?"</h1>'
            '<p class="sub">Who said what between December 2024 and April 2025, with the date each '
            'statement was first reported. The Speaker\'s wording moved the most; the students and '
            'the University of Belgrade said throughout that the demands were not met.</p>'
            + legend_html([("affirms", "all fulfilled"), ("partial", "partly"),
                           ("hedged", "hedged"), ("denies", "not fulfilled")])
            + timeline_svg("P2", datetime(2024, 12, 5, tzinfo=UTC), datetime(2025, 4, 30, tzinfo=UTC),
                           1072, row_h=50, max_actors=20)
            + '<p class="src">The Novi Sad technical and Civil Engineering students\' denials concern '
              'the documentation demand only. Source: stance-ledger answer key, built from nine '
              'Serbian outlets (canopy-collapse-news v1.1.0).</p>')
    return page(body)


# ------------------------------------------------------------------------- survival

def survival_series() -> dict:
    rows = json.loads((ROOT / "runs" / "judge" / "survival.json").read_text())
    agg: dict = {}
    for r in rows:
        a = agg.setdefault(r["arm"], {}).setdefault(r["step"], [0, 0])
        a[0] += sum(v == "attributed" for v in r["labels"].values())
        a[1] += len(r["labels"])
    return {arm: [(step_end(k), v[0] / v[1]) for k, v in sorted(s.items())] for arm, s in agg.items()}


def survival_svg(width: int, height: int = 520, fs: int = 19, annotate: bool = True,
                 label_w: int = 250) -> str:
    S = survival_series()
    left, right, top, bottom = 70, width - label_w, 20, height - 50
    t0, t1 = datetime(2024, 11, 10, tzinfo=UTC), datetime(2025, 5, 4, tzinfo=UTC)

    def x(t):
        return left + (t - t0).total_seconds() / (t1 - t0).total_seconds() * (right - left)

    def y(v):
        return bottom - v / 0.8 * (bottom - top)

    p = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    for v in (0, .2, .4, .6, .8):
        p.append(f'<line x1="{left}" x2="{right}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{T["rule"]}" stroke-width="1"/>')
        p.append(f'<text x="{left-12}" y="{y(v)+6:.1f}" font-size="{fs-3}" fill="{T["faint"]}" text-anchor="end">{int(v*100)}%</text>')
    m = datetime(2024, 12, 1, tzinfo=UTC)
    while m <= t1:
        p.append(f'<text x="{x(m):.1f}" y="{height-14}" font-size="{fs-3}" fill="{T["faint"]}" text-anchor="middle">{m:%b}</text>')
        m = datetime(m.year + (m.month == 12), m.month % 12 + 1, 1, tzinfo=UTC)
    labels = {"ledger": "Stance ledger", "summary_briefed": "Summary with a brief",
              "summary_unbriefed": "Rolling summary"}
    widths = {"ledger": 4, "summary_briefed": 3, "summary_unbriefed": 3}
    ends = []
    for arm in ("summary_unbriefed", "summary_briefed", "ledger"):
        pts = S[arm]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for i, (t, v) in enumerate(pts))
        p.append(f'<path d="{d}" fill="none" stroke="{ARM_COLOR[arm]}" '
                 f'stroke-width="{widths[arm]}" stroke-linejoin="round" stroke-linecap="round"/>')
        for t, v in pts:
            p.append(f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="5" fill="{ARM_COLOR[arm]}" stroke="{T["paper"]}" stroke-width="2"/>')
        ends.append((arm, pts[-1]))
    # end labels, nudged apart
    ys = sorted(((y(v), arm, v) for arm, (_, v) in ends))
    placed = []
    for yy, arm, v in ys:
        if placed and yy - placed[-1] < 64:
            yy = placed[-1] + 64
        placed.append(yy)
        p.append(f'<text x="{right+18}" y="{yy-2:.1f}" font-size="{fs+9}" font-weight="700" '
                 f'font-family="Bricolage Grotesque" fill="{T["ink"]}">{round(v*100)}%</text>')
        p.append(f'<text x="{right+18}" y="{yy+20:.1f}" font-size="{fs-3}" fill="{T["muted"]}">{labels[arm]}</text>')
    if annotate:
        t_feb, v_feb = S["summary_unbriefed"][7]
        p.append(f'<text x="{x(t_feb):.1f}" y="{y(v_feb)+34:.1f}" font-size="{fs-3}" fill="{T["muted"]}" text-anchor="middle">{t_feb.day} {t_feb:%b}: {round(v_feb*100)}% left</text>')
    p.append("</svg>")
    return "".join(p)


def survival_html() -> str:
    body = ('<h1>How much of "who said what" each memory still holds</h1>'
            '<p class="sub">Every two weeks, a judge model checked which of the statements made so '
            'far were still in each memory with the right speaker. All three memories got the '
            'same news.</p>' + survival_svg(1072)
            + '<p class="src">137 statements on four contested questions, 1 Nov 2024 to 30 Apr 2025. '
              'Judge: Claude Opus 5.5.</p>')
    return page(body)


def page(body: str, extra_css: str = "") -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}{extra_css}</style>"
            f"</head><body><div class='fig' id='fig' style='width:1200px'>{body}</div></body></html>")


# ------------------------------------------------------------------------- render

def render(pages: dict[str, str], out: Path, chromium: str | None) -> None:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=chromium) if chromium else pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 800}, device_scale_factor=2)
        for name, html in pages.items():
            (out / f"{name}.html").write_text(html)
            pg.set_content(html, wait_until="networkidle")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(300)
            pg.locator("#fig").screenshot(path=str(out / f"{name}.png"))
        b.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium")
    a = ap.parse_args()
    render({"crowds": crowds_html(), "sound_device": sound_html(), "demands": demands_html(),
            "survival": survival_html()}, FIG, a.chromium)


if __name__ == "__main__":
    main()
