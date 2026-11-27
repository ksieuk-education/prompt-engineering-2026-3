"""Полнотекстовый поиск по репликам технической стенограммы Apollo 11."""

import gzip
import json
import re
import sqlite3
from bisect import bisect_left
from functools import lru_cache
from itertools import islice
from urllib.parse import quote

from . import mission_time
from .archive import ROOT

SOURCE = "https://www.nasa.gov/wp-content/uploads/static/history/alsj/a11/a11transcript_tec.html"
SCAN_253 = "https://www.nasa.gov/wp-content/uploads/2026/01/as11-tec.pdf#page=255"
STAMP = re.compile(r"^(\d{2}) (\d{2}) (\d{2}) (\d{2})(?: (.*))?$")
ROLES = {
    "CDR": "командир Нил Армстронг",
    "LMP": "пилот лунного модуля Эдвин Олдрин",
    "CMP": "пилот командного модуля Майкл Коллинз",
    "CC": "оператор связи в Хьюстоне",
}
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "s",
    "that",
    "the",
    "to",
    "was",
    "were",
    "we",
    "with",
    "you",
}


@lru_cache(maxsize=1)
def pages() -> dict:
    with gzip.open(
        ROOT / "data/field/transcript-pages.json.gz", "rt", encoding="utf-8"
    ) as file:
        return json.load(file)


@lru_cache(maxsize=1)
def supplement():
    return json.loads((ROOT / "data/field/transcript-491.json").read_text())


def timed_entries(blocks):
    for paragraph, block in enumerate(blocks):
        lines = block.splitlines()
        heads = [
            (i, stamp)
            for i, line in enumerate(lines)
            if (stamp := STAMP.fullmatch(line))
        ]
        for n, (i, head) in enumerate(heads):
            end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
            if i + 1 < end:
                yield head, " ".join(lines[i + 1 : end]), (paragraph, i + 1, end)


@lru_cache(maxsize=1)
def indexed_edition():
    result = []
    positions = []
    extra = supplement()
    # Дополнение получает новые ID. Старые ссылки на реплики основного OCR сохраняются.
    for page, blocks in [*pages().items(), (str(extra["page"]), extra["paragraphs"])]:
        for head, text, position in timed_entries(blocks):
            positions.append(position)
            clock = mission_time.elapsed(head[0][:11])
            speaker = head[5] or ""
            code = speaker.split(" ", 1)[0]
            result.append(
                {
                    "id": len(result) + 1,
                    "page": int(page),
                    "get": clock,
                    "speaker": speaker,
                    "role": ROLES.get(code, ""),
                    "text": text,
                    **({"printed_clock": head[0][:11]} if clock is None else {}),
                }
            )
    mission_time.apply_scan_readings(result)
    mission_time.mark_discontinuities(result)
    return result, positions


def catalogue() -> list[dict]:
    return indexed_edition()[0]


def passage_position(number: int, line_id: int) -> dict | None:
    rows, positions = indexed_edition()
    if not 1 <= line_id <= len(rows) or rows[line_id - 1]["page"] != number:
        return None
    paragraph, start, end = positions[line_id - 1]
    return {"id": line_id, "paragraph": paragraph, "start_line": start, "end_line": end}


@lru_cache(maxsize=1)
def index():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute(
        "CREATE VIRTUAL TABLE speech USING fts5(words, speaker UNINDEXED, page UNINDEXED, tokenize='porter unicode61')"
    )
    with db:
        db.executemany(
            "INSERT INTO speech(rowid, words, speaker, page) VALUES (?, ?, ?, ?)",
            (
                (row["id"], row["text"], row["speaker"].split(" ", 1)[0], row["page"])
                for row in catalogue()
            ),
        )
    db.execute("PRAGMA query_only=ON")
    return db


def search_transcript(
    query: str,
    limit: int = 3,
    speaker: str = "",
    exact: bool = False,
    page: int | None = None,
    clock: str = "",
) -> dict:
    """Проверить порядок слов, затем пересечение значимых слов. Пользовательский текст не является FTS-выражением."""
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    keywords = list(dict.fromkeys(t for t in tokens if t not in STOP_WORDS))
    result = {
        "query": query,
        "matches": [],
        "edition_pages": len(pages()),
        "edition_lines": len(catalogue()),
    }
    if clock or mission_time.DIRECT.fullmatch(query):
        return {
            **result,
            **mission_time.search(
                catalogue(),
                clock or query,
                phrase=query if clock else "",
                speaker=speaker,
                page=page,
            ),
        }
    if not keywords:
        return {**result, "mode": "no_terms"}
    phrase = " ".join(tokens)
    queries = [("phrase", '"' + " ".join(tokens[:18]) + '"')]
    if not exact and len(keywords) > 1:
        queries.append(("words", " AND ".join(f'"{word}"' for word in keywords[:18])))
    limit = min(5, max(1, limit))
    for mode, expression in queries:
        ids = index().execute(
            "SELECT rowid FROM speech WHERE speech MATCH ? AND (?='' OR speaker=?) AND (? IS NULL OR page=?) ORDER BY rank, rowid",
            (expression, speaker, speaker, page, page),
        )
        found = (catalogue()[i - 1] for (i,) in ids)
        if exact:
            # Porter также находит слова с общим корнем. Для цитаты сверяем сами слова.
            found = (
                r
                for r in found
                if " " + phrase + " "
                in " " + " ".join(re.findall(r"[a-z0-9]+", r["text"].lower())) + " "
            )
        matches = list(islice(found, limit))
        if matches:
            return {
                **result,
                "mode": mode,
                "matches": matches,
            }
    return {**result, "mode": "no_match"}


def adjacent(line_id: int, offset: int) -> dict | None:
    rows = catalogue()
    if not 1 <= line_id <= len(rows):
        return None
    ordered = reading_order()
    key = (rows[line_id - 1]["page"], line_id)
    pos = bisect_left(ordered, key) + offset
    return rows[ordered[pos][1] - 1] if 0 <= pos < len(ordered) else None


@lru_cache(maxsize=1)
def reading_order():
    return sorted((r["page"], r["id"]) for r in catalogue())


def source_page(number: int) -> dict | None:
    blocks = pages().get(str(number))
    if blocks is None:
        return None
    if number == 253:
        return {
            "page": number,
            "paragraphs": blocks,
            "source": SCAN_253,
            "local_scan": "/field-audio/nasa-page-253.pdf",
            "edition_note": "На скане между строками 03 11 26 40 и 03 11 26 44 напечатано 02 11 26 41. День сохранен как в источнике.",
        }
    if number == supplement()["page"]:
        return {
            key: supplement()[key]
            for key in ("page", "paragraphs", "local_scan", "source", "preview")
        } | {
            "edition_note": "Текст сверен с отдельным полным сканом. На этой странице в основном OCR стоит помета о поврежденном файле."
        }
    return {
        "page": number,
        "paragraphs": blocks,
        "source": SOURCE,
        **mission_time.scan_page(number),
    }


def page_info(number: int) -> dict:
    page = source_page(number)
    if page is None:
        return {
            "page": number,
            "status": "missing",
            "detail": "В этом издании страницы пронумерованы от 1 до 624.",
        }
    lines = [r for r in catalogue() if r["page"] == number]
    detail = f"На странице {number} размечено реплик: {len(lines)}."
    if page.get("edition_note"):
        detail += " " + page["edition_note"]
    return {
        "page": number,
        "status": "available",
        "lines": len(lines),
        "detail": detail,
        "source": page["source"],
    }


def row_link(row: dict) -> str:
    # Текстовый фрагмент адресует оригинальную HTML-страницу, у которой нет якорей отдельных реплик.
    if row["page"] == supplement()["page"]:
        return supplement()["source"]
    if row["page"] == 253:
        return SCAN_253
    if scan := mission_time.scan_page(row["page"]):
        return scan["source"]
    start = " ".join(row["text"].split()[:9])
    return SOURCE + "#:~:text=" + quote(start, safe="")
