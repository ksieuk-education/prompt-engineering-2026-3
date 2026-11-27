"""Архив учебных записей. Метки ленты заданы в секундах от начала файла."""

import json
import math
import re
import sys
import wave
from array import array
from collections import Counter
from functools import lru_cache
from pathlib import Path

import snowballstemmer

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    case["id"]: case for case in json.loads((ROOT / "data/cases.json").read_text())
}
SKILLS = {
    "check_clock": "Сверка часов",
    "check_gap": "Проверка длительности",
    "match_sound": "Поиск по звуку",
}
STEMMER = snowballstemmer.stemmer("russian")
STOP = {
    "это",
    "этот",
    "на",
    "у",
    "с",
    "по",
    "за",
    "в",
    "во",
    "к",
    "и",
    "а",
    "но",
    "для",
    "при",
    "из",
    "то",
    "что",
    "как",
    "ли",
    "бы",
    "со",
    "же",
    "был",
    "была",
    "о",
    "об",
    "он",
    "она",
    "от",
    "до",
    "какой",
    "какая",
    "какое",
    "какие",
    "между",
    "точно",
    "именно",
    "можно",
    "верно",
    "еще",
}


@lru_cache(maxsize=4096)
def stem(word: str) -> str:
    return STEMMER.stemWord(word)


VOCABULARY = {
    "подпись": "подписал подписать подписан подписана подпись подписи расписывался",
    "задержка": "задержка опоздание опоздал опоздать опаздывать позднее позже",
    "объяснение": "причина объяснение почему вызвано",
    "пропуск": "отсутствующий исчезнуть исчезло пропасть пропало утрата утраченный вырезать потеря потерянный",
    "привязка": "синхронизация привязка опора сопоставление синхронизировать",
    "аплодисменты": "аплодисменты хлопки овация",
}
CONCEPT = {
    stem(word): concept
    for concept, words in VOCABULARY.items()
    for word in words.split()
}


def terms(text: str) -> list[str]:
    words = re.findall(r"[а-яa-z0-9]+", text.lower().replace("ё", "е"))
    stems = [stem(w) for w in words if w not in STOP]
    return stems + ["@" + CONCEPT[s] for s in stems if s in CONCEPT]


@lru_cache
def index(case_id: str):
    documents = CASES[case_id]["documents"]
    counters = [
        Counter(terms(d["title"] + " " + d["kind"] + " " + d["text"]))
        for d in documents
    ]
    frequency = Counter(token for row in counters for token in row)
    return counters, frequency, sum(map(Counter.total, counters)) / len(counters)


def search(case_id: str, query: str) -> list[dict]:
    """BM25 по русским основам слов. Каждый результат содержит первичный текст."""
    docs = CASES[case_id]["documents"]
    counts, frequency, average = index(case_id)
    hits = []
    for doc, row in zip(docs, counts):
        score = 0.0
        for word in set(terms(query)) & row.keys():
            idf = math.log(
                1 + (len(docs) - frequency[word] + 0.5) / (frequency[word] + 0.5)
            )
            score += (
                idf
                * row[word]
                * 2.2
                / (row[word] + 1.2 * (0.25 + 0.75 * row.total() / average))
            )
        if score > 0:
            hits.append((score, doc))
    return [doc for _, doc in sorted(hits, key=lambda hit: -hit[0])[:3]]


def document(case_id: str, doc_id: str) -> dict | None:
    return next(
        (
            doc
            for doc in CASES[case_id]["documents"]
            if doc["id"] == doc_id.upper().strip()
        ),
        None,
    )


def skill(name: str) -> dict:
    if name not in SKILLS:
        return {"error": "Выберите одну из памяток.", "available": SKILLS}
    return {
        "name": name,
        "title": SKILLS[name],
        "text": (ROOT / "skills" / f"{name}.md").read_text(),
    }


@lru_cache
def peaks(case_id: str) -> list[float]:
    with wave.open(str(ROOT / "data/tapes" / f"{case_id}.wav")) as recording:
        samples = array("h")
        samples.frombytes(recording.readframes(recording.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
    divisions = 430
    return [
        round(
            max(
                map(
                    abs,
                    samples[
                        i * len(samples) // divisions : (i + 1)
                        * len(samples)
                        // divisions
                    ],
                )
            )
            / 32768,
            3,
        )
        for i in range(divisions)
    ]


def public_case(case_id: str) -> dict:
    case = CASES[case_id]
    return {
        **{
            key: case[key]
            for key in (
                "id",
                "code",
                "title",
                "place",
                "date",
                "brief",
                "questions",
                "duration",
                "markers",
                "documents",
            )
        },
        "peaks": peaks(case_id),
        "audio": f"/tapes/{case_id}.wav",
    }
