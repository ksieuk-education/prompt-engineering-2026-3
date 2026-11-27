"""Сравнить образцы из локального WAV с одним или несколькими другими WAV."""

import argparse
import json
from pathlib import Path

from studio.audio_search import MIN_SCORE, WINDOW, read_audio
from studio.recordings import SPECTRAL_THRESHOLD, compare_recordings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidates", nargs="+", type=Path)
    parser.add_argument(
        "--at",
        nargs="+",
        type=float,
        required=True,
        help="Позиции образцов в исходном WAV, секунды",
    )
    parser.add_argument("--duration", type=float, default=WINDOW)
    parser.add_argument(
        "--speed-scan",
        action="store_true",
        help="Искать копию с постоянным изменением скорости в пределах ±4 %",
    )
    parser.add_argument("--out", type=Path, help="Сохранить измерения в JSON")
    args = parser.parse_args()
    source = read_audio(args.reference)
    report = {
        "reference": args.reference.name,
        "thresholds": {"waveform": MIN_SCORE, "spectrum": SPECTRAL_THRESHOLD},
        "candidates": [],
    }
    for path in args.candidates:
        target = read_audio(path)
        observations = [
            compare_recordings(
                source,
                target,
                at,
                args.duration,
                same_tape=args.reference.samefile(path),
                scan_speed=args.speed_scan,
            )
            for at in args.at
        ]
        report["candidates"].append({"file": path.name, "observations": observations})
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
