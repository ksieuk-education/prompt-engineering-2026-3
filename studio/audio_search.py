"""Поиск образца в звуковой волне. Описи катушек в вычислении не участвуют."""

from math import gcd, isfinite
from pathlib import Path
from typing import Literal

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, find_peaks, resample_poly

from .archive import CASES, ROOT

RATE = 8000
WINDOW = 1.6
MIN_RMS = 0.014
MIN_SCORE = 0.87
Scope = Literal["case", "archive"]


def read_audio(path: Path) -> np.ndarray:
    """Привести моно- или многоканальный WAV к общей частоте и шкале амплитуд."""
    rate, pcm = wavfile.read(path)
    samples = pcm.astype(np.float64)
    if pcm.dtype.kind in "iu":
        scale = 2 ** (pcm.dtype.itemsize * 8 - 1)
        if pcm.dtype.kind == "u":
            samples -= scale
        samples /= scale
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError("WAV должен содержать конечные числовые отсчеты.")
    if rate == RATE:
        return samples
    divisor = gcd(rate, RATE)
    return resample_poly(samples, RATE // divisor, rate // divisor)


def read_tape(case_id: str) -> np.ndarray:
    return read_audio(ROOT / "data" / "tapes" / (case_id + ".wav"))


def waveform_scores(track: np.ndarray, excerpt: np.ndarray) -> np.ndarray:
    """Нормированная корреляция для каждого полного окна исходного трека."""
    size = len(excerpt)
    if not size or len(track) < size:
        return np.empty(0)
    centered = excerpt - excerpt.mean()
    energy = np.dot(centered, centered)
    if energy < size * MIN_RMS**2:
        return np.empty(0)
    sums = np.r_[0.0, np.cumsum(track, dtype=np.float64)]
    squares = np.r_[0.0, np.cumsum(track * track, dtype=np.float64)]
    local_energy = (
        squares[size:] - squares[:-size] - np.square(sums[size:] - sums[:-size]) / size
    )
    sufficient = local_energy >= size * MIN_RMS**2
    numerator = correlate(track, centered, mode="valid", method="fft")
    scores = np.zeros(len(numerator))
    np.divide(
        abs(numerator),
        np.sqrt(energy * np.maximum(local_energy, 0)),
        out=scores,
        where=sufficient,
    )
    return scores


def correlate_excerpt(
    track: np.ndarray, excerpt: np.ndarray, origin: int | None = None
):
    """Найти отдельные повторы, исключив сам образец из выдачи."""
    size = len(excerpt)
    scores = waveform_scores(track, excerpt)
    if not len(scores):
        return []
    if origin is not None:
        # Любое окно с общими отсчетами дало бы совпадение образца с самим собой.
        scores[max(0, origin - size + 1) : origin + size] = 0.0
    # Дополнение учитывает совпадения ровно на первом или последнем допустимом отсчете.
    indices, _ = find_peaks(
        np.r_[-np.inf, scores, -np.inf], height=MIN_SCORE, distance=size
    )
    return [(int(i - 1), min(1.0, float(scores[i - 1]))) for i in indices]


def tape_position(second: float) -> str:
    minutes, hundredths = divmod(round(second * 100), 6000)
    whole, fraction = divmod(hundredths, 100)
    tail = f",{fraction:02d}" if fraction else ""
    return f"{minutes:02d}:{whole:02d}{tail}"


def match_sound(case_id: str, start_seconds: float, scope: Scope = "archive") -> dict:
    if case_id not in CASES or scope not in ("case", "archive"):
        raise ValueError("Неизвестное дело или область поиска.")
    origin_tape = read_tape(case_id)
    size = round(WINDOW * RATE)
    base = {
        "kind": "audio",
        "label": "Сравнение фонограмм",
        "sources": [],
        "case_id": case_id,
        "reference_second": start_seconds,
        "window_seconds": WINDOW,
        "scope": scope,
        "minimum_score": MIN_SCORE,
        "matches": [],
    }
    if (
        not isfinite(start_seconds)
        or start_seconds < 0
        or round(start_seconds * RATE) + size > len(origin_tape)
    ):
        return {
            **base,
            "status": "invalid_window",
            "value": "Образец выходит за край",
            "detail": "Поставьте курсор так, чтобы до конца оставалось не меньше 1,6 с.",
        }
    start = round(start_seconds * RATE)
    excerpt = origin_tape[start : start + size]
    if excerpt.std() < MIN_RMS:
        return {
            **base,
            "status": "quiet",
            "value": "Образец слишком тихий",
            "detail": "В этом окне слишком мало сигнала для сравнения. Выберите слышимое событие.",
        }
    matches = []
    case_ids = list(CASES) if scope == "archive" else [case_id]
    for key in case_ids:
        target = origin_tape if key == case_id else read_tape(key)
        for index, score in correlate_excerpt(
            target, excerpt, start if key == case_id else None
        ):
            matches.append(
                {
                    "case_id": key,
                    "code": CASES[key]["code"],
                    "second": round(index / RATE, 3),
                    "score": round(score, 4),
                }
            )
    matches.sort(key=lambda item: (-item["score"], item["case_id"], item["second"]))
    if not matches:
        return {
            **base,
            "status": "no_match",
            "value": "Похожих фрагментов не найдено",
            "detail": f"Проверено катушек: {len(case_ids)}. При пороге {MIN_SCORE:.2f} других совпадений нет.",
        }
    places = ", ".join(
        f"{m['code']} на {tape_position(m['second'])}" for m in matches[:8]
    )
    return {
        **base,
        "status": "matched",
        "matches": matches[:8],
        "value": f"Найдено совпадений: {len(matches)}",
        "detail": f"Похожий звук найден: {places}. Позиции указаны от начала файлов.",
    }
