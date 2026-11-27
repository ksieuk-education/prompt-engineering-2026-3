import numpy as np
import pytest

from studio.audio_search import correlate_excerpt, match_sound, tape_position


def test_scan_uses_audio_samples_at_arbitrary_positions_and_boundaries():
    rng = np.random.default_rng(3401)
    excerpt = rng.normal(0, 0.12, 400)
    track = rng.normal(0, 0.004, 5200)
    # Первая копия инвертирована и тише, вторая содержит постоянное смещение и шум.
    for start, gain, offset in [(0, -0.5, 0), (1437, 0.75, 0.18), (4800, 1.0, 0)]:
        track[start : start + len(excerpt)] += gain * excerpt + offset
    matches = correlate_excerpt(track, excerpt, origin=1437)
    assert [i for i, _ in matches] == [0, 4800]
    assert all(score > 0.98 for _, score in matches)


@pytest.mark.parametrize(
    "case,start,scope,expected",
    [
        ("signal", 18, "archive", [("untimed", 12.0)]),
        ("splice", 5, "case", [("splice", 25.0)]),
        ("signal", 18, "case", []),
        ("signal", 4, "archive", []),
    ],
)
def test_searches_in_the_requested_scope(case, start, scope, expected):
    observation = match_sound(case, start, scope)
    assert observation["status"] == ("matched" if expected else "no_match")
    assert [
        (hit["case_id"], hit["second"]) for hit in observation["matches"]
    ] == expected


def test_quiet_samples_and_out_of_range_do_not_claim_a_negative_search():
    assert match_sound("signal", 0)["status"] == "quiet"
    assert match_sound("signal", 33)["status"] == "invalid_window"
    assert tape_position(59.997) == "01:00"
    assert tape_position(12.375) == "00:12,38"
