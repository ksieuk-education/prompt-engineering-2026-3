"""Лексические опоры для проверки результата семантического поиска."""

import re
from functools import lru_cache

import snowballstemmer

from .transcript import STOP_WORDS, index

WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE | re.ASCII)
SEARCH_WORDS = STOP_WORDS | {
    "nasa",
    "apollo",
    "11",
    "transcript",
    "transcription",
    "find",
    "where",
    "which",
    "did",
    "mission",
    "astronaut",
    "about",
    "said",
    "says",
    "what",
}


@lru_cache(maxsize=2048)
def occurrence_count(words: tuple[str, ...]) -> int:
    # Нам нужны только пропуски и выражения, встречающиеся максимум в трех строках.
    expression = '"' + " ".join(words) + '"'
    return len(
        index()
        .execute("SELECT rowid FROM speech WHERE speech MATCH ? LIMIT 4", (expression,))
        .fetchall()
    )


def source_hints(queries, rows):
    keywords = set()
    phrases = set()
    for query in queries:
        words = WORD.findall(query.lower())
        for size in (2, 3):
            for start in range(len(words) - size + 1):
                chunk = tuple(words[start : start + size])
                if all(len(word) >= 3 and word not in SEARCH_WORDS for word in chunk):
                    phrases.add(chunk)
    if queries:
        keywords = {
            word
            for word in WORD.findall(queries[-1].lower())
            if len(word) >= 4 and word not in SEARCH_WORDS
        }
    uncommon = {
        phrase: count
        for phrase in phrases
        if 0 < (count := occurrence_count(phrase)) <= 3
    }
    anchors = []
    for order, row in enumerate(rows):
        tokens = list(WORD.finditer(row["text"]))
        normalized = [word.group().lower() for word in tokens]
        for size in (3, 2):
            for start in range(len(tokens) - size + 1):
                phrase = tuple(normalized[start : start + size])
                if phrase in uncommon:
                    snippet = row["text"][
                        tokens[start].start() : tokens[start + size - 1].end()
                    ]
                    anchors.append(
                        (-size, uncommon[phrase], order, start, row["id"], snippet)
                    )
    choices = {}
    for _, _, _, _, line_id, snippet in sorted(anchors):
        choices.setdefault(line_id, snippet)
    return {
        "missing_keywords": sorted(
            word for word in keywords if occurrence_count((word,)) == 0
        ),
        "keywords": sorted(keywords),
        "anchors": [
            {"id": line_id, "quote": snippet}
            for line_id, snippet in list(choices.items())[:3]
        ],
    }


def supports_vocabulary(hints, text):
    if len(hints.get("missing_keywords", [])) < 2:
        return True
    return bool(set(WORD.findall(text.lower())).intersection(hints["keywords"]))


NUMBER_WORDS = dict(
    zip(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
        ],
        range(11),
        strict=True,
    )
)
RUSSIAN_COUNTS = (
    r"нол[ья]|нул[ьея]",
    r"од(?:ин|на|но|ну|ной|ним|ного)",
    r"дв(?:а|е|ух|умя|ум)",
    r"тр(?:и|ех|емя|ем)",
    r"четыр(?:е|ех|емя|ем)",
    r"пят[ьи]|пятью",
    r"шест[ьи]|шестью",
    r"сем[ьи]|семью",
    r"восемь|восьм[ьи]|восемью",
    r"девят[ьи]|девятью",
    r"десят[ьи]|десятью",
)
NUMBER = r"(?:\d+|" + "|".join(NUMBER_WORDS) + r")"
COUNT = re.compile(
    r"(?<![\w.,-])(?P<value>"
    + NUMBER
    + r")\s+(?P<unit>[a-z]+)(?:\s+of\s+(?P<object>[a-z]+))?\b",
    re.IGNORECASE | re.ASCII,
)


def counted_items(text):
    for match in COUNT.finditer(text):
        word = match["unit"].lower()
        if word in SEARCH_WORDS or word in {
            "or",
            "more",
            "less",
            "hundred",
            "thousand",
            "million",
            "other",
        }:
            continue
        # Приблизительные значения и диапазоны сами по себе не опровергают точное число.
        before = text[max(0, match.start() - 35) : match.start()].lower()
        if re.search(
            r"(?:at least|at most|over|under|more than|less than|about|approximately)\s*$|"
            + NUMBER
            + r"\s*(?:or|to|[-–])\s*$",
            before,
        ):
            continue
        raw = match["value"].lower()
        value = int(raw) if raw.isdecimal() else NUMBER_WORDS[raw]
        key = (word.removesuffix("s"), (match["object"] or "").lower())
        yield key, value, match.group()


def quantity_difference(question, translation, passage):
    """Сверять одно и то же счетное выражение, только если число было в исходном вопросе."""
    question = question.lower().replace("ё", "е")
    original = {int(x) for x in re.findall(r"(?<![\w.,-])\d{1,6}(?![\w.,-])", question)}
    original.update(
        n
        for n, pattern in enumerate(RUSSIAN_COUNTS)
        if re.search(r"\b(?:" + pattern + r")\b", question)
    )
    if not original:
        return None
    printed = list(counted_items(passage))
    for unit, wanted, _ in counted_items(translation):
        if wanted not in original:
            continue
        readings = [(value, words) for item, value, words in printed if item == unit]
        numbers = {value for value, _ in readings}
        if len(numbers) == 1 and wanted not in numbers:
            value, words = readings[0]
            return {"requested": wanted, "printed": value, "words": words}
    return None


ENGLISH = snowballstemmer.stemmer("english")


def compare_quantities(question, queries, rows, page=None):
    translation = " ".join(queries)
    differences = {
        r["id"]: diff
        for r in rows
        if (diff := quantity_difference(question, translation, r["text"]))
    }
    if not differences:
        return {}, set(), None
    # Счетное выражение не помогает отличить два события с чашками кофе.
    counted = {
        w for m in COUNT.finditer(translation) for w in WORD.findall(m.group().lower())
    }
    wanted = {
        w
        for w in WORD.findall(translation.lower())
        if len(w) >= 4 and w not in SEARCH_WORDS | counted
    }
    context = set(ENGLISH.stemWords(sorted(wanted)))
    terms = {
        r["id"]: context.intersection(
            ENGLISH.stemWords(WORD.findall(r["text"].lower()))
        )
        for r in rows
    }
    best = max(differences, key=lambda i: len(terms[i]))
    # У другой строки совпало число, но как минимум две характерные детали ситуации
    # есть только рядом с расходящимся числом. Склеивать такие реплики нельзя.
    other_events = {
        i for i in terms if terms[i] < terms[best] and len(terms[best] - terms[i]) >= 2
    }
    show = best if page is not None or len(terms[best]) >= 2 else None
    return differences, other_events, show
