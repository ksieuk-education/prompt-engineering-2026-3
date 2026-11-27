import pytest

from studio import repeats


def test_matched_tapes_use_independent_clock_sources_in_both_directions():
    forward = repeats.compare_repeat_clocks("signal", 18)
    assert forward["source"]["clock"]["value"] == "21:17:24"
    assert (
        forward["target"]["case_id"] == "untimed"
        and forward["target"]["clock"]["status"] == "insufficient"
    )
    assert {"A2", "A3", "C2", "C3"} <= set(forward["sources"])
    back = repeats.compare_repeat_clocks(
        "untimed", 12, candidate_case="signal", candidate_second=18
    )
    assert back["target"] == forward["source"] and back["source"] == forward["target"]
    assert repeats.remember([back])["candidate_case"] == "signal"


def test_cannot_derive_a_clock_for_a_missed_or_unlisted_sound():
    assert repeats.compare_repeat_clocks("signal", 4)["status"] == "no_match"
    assert (
        repeats.compare_repeat_clocks("signal", 18, candidate_case="splice")["status"]
        == "not_listed"
    )
    assert (
        repeats.compare_repeat_clocks("splice", 5, other_tape=True)["status"]
        == "no_other_tape"
    )
    assert (
        repeats.clock_for_position("untimed", 12.2)["clock"]["status"] == "unlabelled"
    )
    with pytest.raises(ValueError):
        repeats.compare_repeat_clocks("signal", 18, candidate_second=float("nan"))


def test_matching_two_bells_reads_each_documented_wall_time():
    result = repeats.compare_repeat_clocks("splice", 5, "case")
    assert (result["source"]["clock"]["value"], result["target"]["clock"]["value"]) == (
        "19:05:12",
        "19:05:37",
    )
    assert set(result["sources"]) == {"B1", "B2"}


def test_same_code_with_multiple_matches_requires_a_tape_position(monkeypatch):
    monkeypatch.setattr(
        repeats,
        "match_sound",
        lambda *args: {
            "status": "matched",
            "matches": [
                {"case_id": "splice", "code": "ФН-027", "second": 5.0, "score": 0.998},
                {"case_id": "splice", "code": "ФН-027", "second": 25.0, "score": 0.997},
            ],
        },
    )
    first = repeats.compare_repeat_clocks("signal", 18, candidate_case="splice")
    assert first["status"] == "choose" and len(first["options"]) == 2
    args, _ = repeats.followup("ФН-027 на 00:25", repeats.remember([first]))
    assert (
        repeats.compare_repeat_clocks(**args)["target"]["clock"]["value"] == "19:05:37"
    )
    assert repeats.followup("Что было на конверте?", repeats.remember([first])) is None
    assert repeats.followup("Во сколько был эфир повтора?", {}) is None
