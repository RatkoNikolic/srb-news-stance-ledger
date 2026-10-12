from datetime import UTC, datetime

from stance_ledger.ledger import same, stance_value, timelines
from stance_ledger.score import actor_match, norm_stance, score_one, stance_match
from stance_ledger.windows import knowledge_time, sentences


def test_sentences_keep_dates_and_times_together():
    text = "Protest je počeo 15. marta u 11.52 časova. Studenti su rekli da nastavljaju."
    spans = sentences(text)
    assert len(spans) == 2
    assert text[spans[0][0]:spans[0][1]].endswith("časova.")


def test_live_blog_known_next_morning():
    t = datetime(2025, 3, 15, 10, 0, tzinfo=UTC)
    kt, live = knowledge_time(t, "Protest 15. marta UŽIVO")
    assert live and kt > t and kt.astimezone().day in (16,)
    assert knowledge_time(t, "Obična vest") == (t, False)


def test_numbers_within_ten_percent_are_the_same_stance():
    assert same("107,000", "110,000")
    assert same("275,000-325,000", "300,000")
    assert not same("55,000", "145,000")


def _rec(actor, stance, day, outlet="a", prop="P5"):
    return {"actor": actor, "proposition": prop, "stance": stance, "step": day // 2,
            "known_at": datetime(2025, 3, day, tzinfo=UTC), "outlet_id": outlet,
            "paraphrase_en": "x", "record_id": f"{actor}{day}"}


def test_timeline_records_a_stance_change_and_never_merges_actors():
    recs = [_rec("ministry_interior", "denies", 16), _rec("ministry_interior", "denies", 17, "b"),
            _rec("ministry_interior", "affirms", 17, "c"),      # outvoted within its step
            _rec("ministry_interior", "partial", 19), _rec("students_blockade", "affirms", 16)]
    tl = timelines(recs, 91)["P5"]
    assert [s["stance"] for s in tl["ministry_interior"]] == ["denies", "partial"]
    assert len(tl["ministry_interior"][0]["outlets"]) == 2
    assert tl["students_blockade"][0]["stance"] == "affirms"


def test_stance_value_prefers_numbers():
    r = {"stance": "value", "category": "crowd_size", "number_low": 55000, "number_high": 55000}
    assert stance_value(r) == "55,000"


def test_score_counts_current_stale_and_change():
    g = [{"actor": "ministry_interior", "stance": "denies", "value": None,
          "t": datetime(2025, 3, 16, tzinfo=UTC)},
         {"actor": "ministry_interior", "stance": "partial", "value": None,
          "t": datetime(2025, 3, 19, tzinfo=UTC)}]
    ans = {"positions": [{"actor": "ministry_interior", "stance": "denies", "since": "x"}],
           "changes": []}
    s = score_one(ans, g, 70)          # step 70 ends 2025-03-12+ … well after both
    assert s["gold_actors"] == 1 and s["stale"] == 1 and s["recall_hits"] == 0
    ans2 = {"positions": [{"actor": "ministry_interior", "stance": "partial", "since": "x"}],
            "changes": [{"actor": "ministry_interior", "from_stance": "denies",
                         "to_stance": "partial"}]}
    s2 = score_one(ans2, g, 70)
    assert s2["recall_hits"] == 1 and s2["changes_detected"] == 1


def test_matching_helpers():
    assert actor_match("students:FTN Novi Sad", "students:Faculty FTN Novi Sad")
    assert not actor_match("students:FTN Novi Sad", "party:FTN")
    assert norm_stance({"low": 275000, "high": 325000}) == "275000-325000"
    assert stance_match("107000", "107,000")
