import numpy as np
import pytest
from scipy.io import wavfile

from studio.archive import ROOT
from studio.audio_search import RATE, read_audio
from studio.recordings import compare_public, compare_recordings


def test_real_recording_has_spectral_candidate_but_not_a_waveform_match():
    field = ROOT / "data/field"
    reference = read_audio(field / "eagle-short.wav")
    same_event = compare_recordings(
        reference, read_audio(field / "eagle-extended.wav"), 2.5
    )
    other_words = compare_recordings(
        reference, read_audio(field / "small-step.wav"), 2.5
    )
    assert not same_event["waveform"]["passes"]
    assert (
        same_event["spectrum"]["passes"]
        and abs(same_event["spectrum"]["second"] - 3.41) <= 0.03
    )
    assert (
        not other_words["spectrum"]["passes"] and not other_words["waveform"]["passes"]
    )


def test_quiet_short_and_self_comparisons_are_distinct():
    rng = np.random.default_rng(82)
    recording = rng.normal(0, 0.1, 2 * RATE)
    assert compare_recordings(np.zeros(2 * RATE), recording, 0)["status"] == "quiet"
    assert (
        compare_recordings(recording, recording[: RATE // 4], 0)["status"]
        == "short_target"
    )
    masked = compare_recordings(recording, recording, 0, 2, same_tape=True)
    assert masked["spectrum"] is None and masked["waveform"] is None
    with pytest.raises(ValueError, match="конец"):
        compare_recordings(recording, recording, 1)


def test_stereo_pcm_and_sample_rate_are_normalized(tmp_path):
    sample_rate = 16000
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(sample_rate) / sample_rate)
    stereo = (np.column_stack((tone, tone * 0.5)) * 32768).astype(np.int16)
    path = tmp_path / "stereo.wav"
    wavfile.write(path, sample_rate, stereo)
    mono = read_audio(path)
    assert len(mono) == RATE and 0.22 < mono.max() < 0.23


def test_speed_search_measures_the_known_copy_and_rejects_unrelated_speech():
    found = compare_public("calibration", 2.50, scan_speed=True)
    speed = found["speed_scan"]
    assert not found["waveform"]["passes"] and speed["passes"]
    assert speed["rate_ratio"] == pytest.approx(1.017, abs=0.0006)
    assert speed["second"] == pytest.approx(0.57 + 2.50 / 1.017, abs=0.003)
    assert speed["window_seconds"] < found["window_seconds"]
    other = compare_public("small-step", 2.50, scan_speed=True)["speed_scan"]
    assert not other["passes"] and other["rate_ratio"] is None
    assert "speed_scan" not in compare_public("calibration", 2.50)


def test_speed_search_excludes_overlapping_self_and_handles_a_shorter_copy():
    rng = np.random.default_rng(404)
    signal = rng.normal(0, 0.13, RATE)
    masked = compare_recordings(signal, signal, 0, 1, same_tape=True, scan_speed=True)
    assert masked["speed_scan"] is None
    from scipy.signal import resample_poly

    faster = resample_poly(signal, 100, 103)
    assert compare_recordings(signal, faster, 0, 1)["status"] == "short_target"
    assert compare_recordings(signal, faster, 0, 1, scan_speed=True)["speed_scan"][
        "passes"
    ]
