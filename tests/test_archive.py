import wave

from studio.archive import CASES, ROOT, document, search
from studio.clock_tools import compare_span, locate_marker, timecode


def test_airtime_uses_observed_anchor():
    result = locate_marker("signal", "ident")
    assert (result["anchor_tape"], result["tape"]) == ("00:04", "00:18")
    assert (result["value"], result["planned"], result["shift_seconds"]) == (
        "21:17:24",
        "21:17:20",
        4,
    )
    assert set(result["sources"]) == {"A1", "A2", "A3"}


def test_tape_interval_works_without_an_airtime_anchor():
    from studio.clock_tools import tape_span

    measured = tape_span("signal", "ident", "sync")
    assert measured["tape_seconds"] == 14 and measured["sources"] == ["A2"]
    assert tape_span("untimed", "noise", "ident")["tape_seconds"] == 9
    assert tape_span("signal", "sync", "sync")["status"] == "insufficient"


def test_span_measures_but_cannot_locate_internal_edit():
    span = compare_span("splice")
    assert (span["air_seconds"], span["tape_seconds"], span["missing_seconds"]) == (
        25,
        20,
        5,
    )
    assert locate_marker("splice", "last")["value"] == "19:05:37"
    assert locate_marker("splice", "room")["status"] == "insufficient"


def test_plan_cannot_set_the_clock():
    result = locate_marker("untimed", "ident")
    assert result["status"] == "insufficient" and result["tape"] == "00:12"
    assert "09:40:00" == result["planned"]
    assert "anchor" not in result and set(result["sources"]) == {"C1", "C2", "C3"}
    assert compare_span("untimed")["status"] == "insufficient"


def test_tape_position_does_not_require_airtime_calibration():
    clock = locate_marker("splice", "room", "tape")
    assert (clock["value"], clock["second"], clock["sources"]) == ("00:12", 12, ["B2"])
    assert "planned" not in clock and "anchor" not in clock
    assert locate_marker("splice", "room")["status"] == "insufficient"


def test_source_questions_and_case_isolation():
    assert search("signal", "почему позывной опоздал")[0]["id"] == "A4"
    assert "B3" in {d["id"] for d in search("splice", "что именно исчезло")}
    assert search("signal", "марсианская оранжерея") == []
    assert document("untimed", "A3") is None
    assert locate_marker("signal", "несуществующая метка")["status"] == "unknown_marker"


def test_tapes_really_contain_the_marked_sounds():
    import struct

    for case in CASES.values():
        with wave.open(str(ROOT / "data/tapes" / (case["id"] + ".wav"))) as wav:
            sample_rate = wav.getframerate()
            assert (
                sample_rate == 16000
                and wav.getnframes() == sample_rate * case["duration"]
            )
            samples = [
                v for (v,) in struct.iter_unpack("<h", wav.readframes(wav.getnframes()))
            ]
        for marker in case["markers"]:
            start = marker["second"] * sample_rate
            assert max(map(abs, samples[start : start + sample_rate * 2])) > 1900, (
                marker
            )
    assert timecode(86403) == "00:00:03"
