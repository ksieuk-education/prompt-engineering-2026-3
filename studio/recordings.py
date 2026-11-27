"""Сопоставление двух оцифровок по отсчетам и по изменению энергии частотных полос."""

from fractions import Fraction
from itertools import pairwise
from math import ceil, isfinite
from typing import Literal

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import ShortTimeFFT, correlate, resample_poly, windows

from .archive import ROOT
from .audio_search import (
    MIN_RMS,
    MIN_SCORE,
    RATE,
    WINDOW,
    read_audio,
    tape_position,
    waveform_scores,
)

HOP = 80
SPECTRAL_THRESHOLD = 0.70
FieldTarget = Literal["eagle-extended", "small-step", "calibration"]
TRANSFORM = ShortTimeFFT(windows.hann(256, sym=False), HOP, RATE, scale_to="magnitude")


def band_energy(samples: np.ndarray) -> np.ndarray:
    # Только полные окна. Начало временной оси совпадает для образца и кандидата.
    half = len(TRANSFORM.win) // 2
    first = ceil(half / HOP)
    stop = (len(samples) - half) // HOP + 1
    if stop <= first:
        return np.empty((0, 0))
    spectrum = TRANSFORM.spectrogram(samples, p0=first, p1=stop)
    edges = np.geomspace(160, 3800, 24)
    bands = []
    for lo, hi in pairwise(edges):
        mask = (TRANSFORM.f >= lo) & (TRANSFORM.f < hi)
        if mask.any():
            bands.append(spectrum[mask].mean(axis=0))
    decibels = 10 * np.log10(np.maximum(bands, 1e-8))
    return gaussian_filter1d(decibels, 1.2, axis=1)


def spectral_scores(track: np.ndarray, excerpt: np.ndarray) -> np.ndarray:
    target, query = band_energy(track), band_energy(excerpt)
    size = query.shape[1]
    if size < 2 or target.shape[1] < size:
        return np.empty(0)
    query -= query.mean(axis=1, keepdims=True)
    total = float(np.sum(query**2))
    if total < 1e-9:
        return np.empty(0)
    sums = np.pad(np.cumsum(target, axis=1), ((0, 0), (1, 0)))
    squares = np.pad(np.cumsum((target**2).sum(axis=0)), (1, 0))
    energy = (
        squares[size:]
        - squares[:-size]
        - np.square(sums[:, size:] - sums[:, :-size]).sum(axis=0) / size
    )
    numerator = sum(
        correlate(a, b, mode="valid", method="fft")
        for a, b in zip(target, query, strict=True)
    )
    return numerator / np.sqrt(total * np.maximum(energy, 1e-9))


def strongest(scores, hop, threshold, origin, size, source_size=None):
    if not len(scores):
        return None
    if origin is not None:
        start = max(0, (origin - size) // hop + 1)
        stop = ceil((origin + (source_size if source_size is not None else size)) / hop)
        scores[start:stop] = -np.inf
    at = int(np.argmax(scores))
    if not np.isfinite(scores[at]):
        return None
    score = float(np.clip(scores[at], -1.0, 1.0))
    return {
        "second": round(at * hop / RATE, 4),
        "score": round(score, 4),
        "passes": score >= threshold,
    }


def scan_waveform_speed(candidate, excerpt, origin=None):
    """Искать постоянное изменение скорости в пределах ±4 % по форме волны."""
    best = None
    best_rate = 10000

    def evaluate(rates):
        nonlocal best, best_rate
        for rate in rates:
            ratio = Fraction(10000, rate).limit_denominator(2000)
            adjusted = (
                excerpt
                if rate == 10000
                else resample_poly(excerpt, ratio.numerator, ratio.denominator)
            )
            peak = strongest(
                waveform_scores(candidate, adjusted),
                1,
                MIN_SCORE,
                origin,
                len(adjusted),
                len(excerpt),
            )
            if peak and (
                best is None
                or (peak["score"], -abs(rate - 10000))
                > (best["score"], -abs(best_rate - 10000))
            ):
                best, best_rate = peak, rate

    evaluate(range(9600, 10401, 20))
    if best is None:
        return None
    # Уточняем максимум, сохраняя границы и определенную заранее цену деления 0,05 %.
    evaluate(
        rate
        for rate in range(max(9600, best_rate - 15), min(10400, best_rate + 15) + 1, 5)
        if rate % 20
    )
    return {
        **best,
        "rate_ratio": best_rate / 10000 if best["passes"] else None,
        "window_seconds": round(len(excerpt) / RATE * 10000 / best_rate, 4)
        if best["passes"]
        else None,
    }


def compare_recordings(
    reference, candidate, at, duration=WINDOW, *, same_tape=False, scan_speed=False
):
    if not isfinite(at) or not isfinite(duration) or at < 0 or duration < 0.3:
        raise ValueError("Нужна неотрицательная позиция и не меньше 0,3 с звука.")
    start, size = round(at * RATE), round(duration * RATE)
    if start + size > len(reference):
        raise ValueError("Образец выходит за конец исходной записи.")
    excerpt = reference[start : start + size]
    result = {
        "reference_second": at,
        "window_seconds": duration,
        "waveform": None,
        "spectrum": None,
    }
    if len(candidate) < (ceil(size / 1.04) if scan_speed else size):
        return {**result, "status": "short_target"}
    if excerpt.std() < MIN_RMS:
        return {**result, "status": "quiet"}
    origin = start if same_tape else None
    wave = strongest(waveform_scores(candidate, excerpt), 1, MIN_SCORE, origin, size)
    spectral = strongest(
        spectral_scores(candidate, excerpt), HOP, SPECTRAL_THRESHOLD, origin, size
    )
    if scan_speed:
        result["speed_scan"] = scan_waveform_speed(candidate, excerpt, origin)
    return {**result, "status": "compared", "waveform": wave, "spectrum": spectral}


def compare_public(candidate: FieldTarget, at: float, scan_speed: bool = False) -> dict:
    recordings = ROOT / "data/field"
    if candidate not in {"eagle-extended", "small-step", "calibration"}:
        raise ValueError("Выберите запись из списка сверки.")
    base = {
        "kind": "public_audio",
        "sources": [],
        "candidate": candidate,
        "reference_second": at,
        "label": "Сверка записей NASA",
        "thresholds": {"waveform": MIN_SCORE, "spectrum": SPECTRAL_THRESHOLD},
    }
    if scan_speed:
        base["thresholds"]["speed_scan"] = MIN_SCORE
    try:
        result = compare_recordings(
            read_audio(recordings / "eagle-short.wav"),
            read_audio(recordings / (candidate + ".wav")),
            at,
            scan_speed=scan_speed,
        )
    except ValueError as err:
        return {
            **base,
            "status": "invalid_window",
            "value": "Проверьте начало образца",
            "detail": str(err),
        }
    if result["status"] != "compared":
        detail = (
            "В выбранном окне слишком мало слышимого сигнала."
            if result["status"] == "quiet"
            else "Вторая запись короче образца."
        )
        return {**base, **result, "value": "Недостаточно звука", "detail": detail}
    values = []
    for method, label in (("waveform", "По волне"), ("spectrum", "По спектру")):
        hit = result[method]
        if not hit:
            values.append(f"{label} подходящего окна нет.")
            continue
        score = f"{hit['score']:.3f}".replace(".", ",")
        location = (
            "кандидат на " + tape_position(hit["second"])
            if hit["passes"]
            else "ниже порога"
        )
        values.append(f"{label} r = {score}, {location}.")
    if scan_speed:
        hit = result["speed_scan"]
        if hit and hit["passes"]:
            change = f"{(hit['rate_ratio'] - 1) * 100:+.2f}".replace(".", ",")
            score = f"{hit['score']:.3f}".replace(".", ",")
            values.append(
                f"При поправке скорости {change} % форма волны совпадает на {tape_position(hit['second'])}, r = {score}."
            )
        else:
            values.append(
                "Перебор скорости от −4 до +4 % совпадения по волне не подтвердил."
            )
    return {
        **base,
        **result,
        "value": "Две записи сравнены",
        "detail": " ".join(values),
    }
