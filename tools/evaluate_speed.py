"""Контроль поиска копии с другой скоростью по двум речевым WAV из открытого архива."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from studio.archive import ROOT
from studio.audio_search import RATE, read_audio
from studio.recordings import compare_recordings

FILES = ROOT / "data/field"
POSITIONS = {"eagle-short": (0.60, 2.58), "small-step": (2.30, 6.70)}
DELAY = 0.57
CALIBRATION_RATE = 1.017


def make_copy(source, rate):
    # Аналоговый эффект моделируем интерполяцией. Поисковик использует другой метод (полифазный фильтр).
    sample_times = np.arange(0, len(source) - 1, rate)
    copied = np.interp(sample_times, np.arange(len(source)), source)
    signal = np.r_[np.zeros(round(DELAY * RATE)), -0.72 * copied]
    noise = np.random.default_rng(1903 + round(rate * 10000)).normal(
        0, 0.006, len(signal)
    )
    return np.clip(signal + noise, -1, 1)


def check_copy(source, target, at, rate):
    result = compare_recordings(source, target, at, scan_speed=True)
    best = result["speed_scan"]
    expected = DELAY + at / rate
    localized = bool(
        best
        and best["passes"]
        and abs(best["second"] - expected) <= 0.003
        and abs(best["rate_ratio"] - rate) <= 0.0006
    )
    in_range = 0.96 <= rate <= 1.04
    return {
        "rate": rate,
        "reference_second": at,
        "expected_second": round(expected, 4),
        "waveform": result["waveform"],
        "spectrum": result["spectrum"],
        "speed_scan": best,
        "in_range": in_range,
        "correct": localized if in_range else not best["passes"],
    }


def measure():
    copies, negatives, published = [], [], []
    originals = {name: read_audio(FILES / (name + ".wav")) for name in POSITIONS}
    for name, source in originals.items():
        for rate in (0.9727, 1.0, CALIBRATION_RATE, 1.0334, 1.066):
            target = make_copy(source, rate)
            for at in POSITIONS[name]:
                copies.append(
                    {"reference": name, **check_copy(source, target, at, rate)}
                )
        other_name = next(key for key in originals if key != name)
        for at in POSITIONS[name]:
            result = compare_recordings(
                source, originals[other_name], at, scan_speed=True
            )
            negatives.append(
                {
                    "reference": name,
                    "candidate": other_name,
                    "at": at,
                    "waveform": result["waveform"],
                    "speed_scan": result["speed_scan"],
                }
            )
    for at in (0.75, 2.50, 3.40):
        result = compare_recordings(
            originals["eagle-short"],
            read_audio(FILES / "eagle-extended.wav"),
            at,
            scan_speed=True,
        )
        published.append(
            {
                "at": at,
                **{
                    method: result[method]
                    for method in ("waveform", "spectrum", "speed_scan")
                },
            }
        )
    drifted = [c for c in copies if c["in_range"] and c["rate"] != 1]
    outside = [c for c in copies if not c["in_range"]]
    return {
        "units": "seconds from the beginning of each WAV",
        "delay": DELAY,
        "waveform_threshold": 0.87,
        "summary": {
            "changed_speed_windows": len(drifted),
            "ordinary_wave_hits": sum(c["waveform"]["passes"] for c in drifted),
            "located_with_speed": sum(c["correct"] for c in drifted),
            "unchanged_controls": sum(c["correct"] for c in copies if c["rate"] == 1),
            "out_of_range_rejected": sum(c["correct"] for c in outside),
            "out_of_range_count": len(outside),
            "other_transmission_hits": sum(
                c["speed_scan"]["passes"] for c in negatives
            ),
            "other_transmission_count": len(negatives),
        },
        "synthetic_copies": copies,
        "other_transmissions": negatives,
        "two_published_editions": published,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, help="Сохранить контрольные измерения в JSON"
    )
    parser.add_argument(
        "--write-copy",
        type=Path,
        help="Пересобрать учебный WAV для прослушивания в интерфейсе",
    )
    args = parser.parse_args()
    if args.write_copy:
        wave = make_copy(read_audio(FILES / "eagle-short.wav"), CALIBRATION_RATE)
        wavfile.write(args.write_copy, RATE, np.rint(wave * 32767).astype(np.int16))
        print(
            f"{args.write_copy.name} SHA-256 {hashlib.sha256(args.write_copy.read_bytes()).hexdigest()}"
        )
    if args.out or not args.write_copy:
        report = measure()
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            args.out.write_text(output)
            print(report["summary"])
        else:
            print(output, end="")


if __name__ == "__main__":
    main()
