"""Создает три авторские учебные фонограммы. Достаточно стандартной библиотеки Python."""

import json
import math
import random
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATE = 16000
TAU = math.tau


def add_tone(track, second, duration, frequency, volume, decay=1.6):
    start = round(second * RATE)
    for i in range(min(round(duration * RATE), len(track) - start)):
        t = i / RATE
        envelope = min(1, t / 0.012, (duration - t) / 0.045) * math.exp(-decay * t)
        track[start + i] += (
            volume
            * envelope
            * (math.sin(TAU * frequency * t) + 0.2 * math.sin(TAU * 2 * frequency * t))
        )


def render(case, seed):
    noise = random.Random(seed)
    frames = RATE * case["duration"]
    track = [
        noise.uniform(-0.011, 0.011) + 0.005 * math.sin(i * TAU * 55 / RATE)
        for i in range(frames)
    ]
    for event in case["markers"]:
        at, sound = event["second"], event["sound"]
        if sound == "reference":
            add_tone(track, at, 0.85, 900, 0.45, 0.15)
        elif sound == "ident":
            for j, freq in enumerate([440, 554.37, 659.25]):
                add_tone(track, at + j * 0.53, 0.95, freq, 0.42)
        elif sound == "music":
            for j, freq in enumerate([329.63, 392, 440, 493.88, 392, 329.63]):
                add_tone(track, at + j * 0.42, 0.8, freq, 0.28)
                add_tone(track, at + j * 0.42, 0.7, freq / 2, 0.2)
        elif sound == "bell":
            for freq, amp in [(520, 0.36), (1275, 0.19), (2087, 0.07)]:
                add_tone(track, at, 2.1, freq, amp, 2.3)
        elif sound == "audience":
            previous = 0
            for i in range(RATE * 5):
                previous = 0.91 * previous + noise.uniform(-0.09, 0.09)
                window = math.sin(math.pi * i / (RATE * 5)) ** 2
                track[at * RATE + i] += previous * window
        else:
            add_tone(track, at, 0.055, 1730, 0.46, 35)
    data = bytearray()
    for y in track:
        data.extend(struct.pack("<h", round(max(-1, min(1, y)) * 32767)))
    dest = ROOT / "data" / "tapes"
    dest.mkdir(exist_ok=True)
    with wave.open(str(dest / (case["id"] + ".wav")), "wb") as file:
        file.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        file.writeframes(data)


if __name__ == "__main__":
    for index, case in enumerate(json.loads((ROOT / "data/cases.json").read_text())):
        render(case, 410 + index)
