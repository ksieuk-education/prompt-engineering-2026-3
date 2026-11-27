"""Работа архивиста с англоязычной стенограммой и соседними репликами."""

import asyncio
import json
import os
import re
from typing import Literal, NamedTuple

import httpx
from pydantic import BaseModel, Field

from . import argos_translation, mission_time, transcript_movement
from .ollama import structured
from .semantic import DOC_ROLE
from .transcript import ROLES, row_link
from .transcript_evidence import compare_quantities, supports_vocabulary
from .transcript_questions import (
    cross_clock,
    direction,
    literal_query,
    matches_identifiers,
    named_speaker,
    opens_page,
    page_number,
    requested_field,
)


class SearchTerms(BaseModel):
    translation: str = Field(min_length=1, max_length=160)
    keywords: str = Field(min_length=1, max_length=85)


class SourceChoice(BaseModel):
    quote: str = Field(max_length=160)
    selected: int


class EvidenceCheck(BaseModel):
    verdict: Literal["relevant", "irrelevant"]


class PassageSearch(NamedTuple):
    matches: list[dict]
    query: str
    mode: str
    quote: str
    review: list[dict]


def counterexample_in(rows):
    return next(
        (
            row
            for row in rows
            if "quantity_difference" in row or "movement_difference" in row
        ),
        None,
    )


async def translate(question, http, host, model):
    schema = SearchTerms.model_json_schema()
    terms = await structured(
        http,
        host + "/api/chat",
        expected=SearchTerms,
        retry_limit=1536,
        json={
            "model": model,
            "stream": False,
            "think": False,
            "format": schema,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You translate Russian descriptions into English to search a historical transcript. "
                        "In translation give a literal English rendering of the words or event being sought. "
                        "Retain the objects and actions, omit the request to find them. Never paraphrase with an English idiom or guess an answer. "
                        "In keywords take two to four distinctive English words from that translation. "
                        "For example, a question about the colour of the ocean gives translation 'the colour of the ocean', keywords 'ocean colour'."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "options": {
                "temperature": 0,
                "seed": 23,
                "num_predict": 220,
                "num_ctx": 2048,
            },
        },
    )
    return list(
        dict.fromkeys(
            s.strip()
            for s in (terms.translation, terms.keywords)
            if re.search("[a-z]", s, re.IGNORECASE)
        )
    )


def excerpt(text, wanted, texts, size=560):
    if len(text) <= size:
        return text
    words = set(re.findall(r"[a-z]{4,}", " ".join(wanted).lower()))
    words.difference_update(
        {
            "apollo",
            "nasa",
            "said",
            "where",
            "about",
            "after",
            "what",
            "find",
            "that",
            "with",
        }
    )
    folded = text.lower()
    anchors = [
        (sum(word in candidate for candidate in texts), -len(word), folded.index(word))
        for word in words
        if word in folded
    ]
    center = min(anchors)[2] if anchors else 0
    start = max(0, min(len(text) - size, center - size // 3))
    return text[start : start + size]


async def choose_source(question, rows, http, host, model, wanted=()):
    if not rows:
        return None, ""
    schema = SourceChoice.model_json_schema()
    schema["properties"]["selected"]["enum"] = list(range(len(rows) + 1))
    texts = [row["text"].lower() for row in rows]
    candidates = [
        {
            "number": number,
            "speaker": row["role"] or row["speaker"],
            "text": excerpt(row["text"], wanted, texts),
        }
        for number, row in enumerate(rows, 1)
    ]
    choice = await structured(
        http,
        host + "/api/chat",
        expected=SourceChoice,
        retry_limit=1536,
        json={
            "model": model,
            "stream": False,
            "think": False,
            "format": schema,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Проверь фрагменты подлинного источника. Найди одну реплику, в которой прямо сказано именно то, о чем спросили. "
                        "Учитывай все детали и говорящего. Общей темы или отдельных совпавших слов недостаточно. "
                        "Если подтверждения нет, верни пустую quote и selected=0. "
                        "Если есть, сначала скопируй в quote два-восемь отличительных английских слов из одной подходящей строки. "
                        "В selected укажи ее короткий number. Цитата должна выражать смысл запрошенного фрагмента. "
                        "Не придумывай цитату. Ответь только JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"вопрос": question, "реплики": candidates}, ensure_ascii=False
                    ),
                },
            ],
            "options": {
                "temperature": 0,
                "seed": 23,
                "num_ctx": 8192,
                "num_predict": 320,
            },
        },
    )

    def normalize(text):
        return " ".join(re.findall(r"[a-z0-9]+", text.lower()))

    evidence = normalize(choice.quote)
    if 1 <= choice.selected <= len(rows) and evidence:
        found = [r for r in rows if f" {evidence} " in f" {normalize(r['text'])} "]
        chosen = rows[choice.selected - 1]
        if chosen in found:
            return chosen, choice.quote
        if len(found) == 1 and len(evidence.split()) >= 2 and len(evidence) >= 10:
            # Модель иногда переносит правильную цитату к номеру соседней строки.
            return found[0], choice.quote
    return None, ""


async def supports_question(question, row, quote, http, host, model):
    result = await structured(
        http,
        host + "/api/chat",
        expected=EvidenceCheck,
        retry_limit=1024,
        json={
            "model": model,
            "stream": False,
            "think": False,
            "format": EvidenceCheck.model_json_schema(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are checking search relevance. A reader wants to locate a particular utterance. "
                        "Decide whether this excerpt answers the content of the request. Its page, time, Apollo 11 setting and "
                        "speaker are supplied by the archive; the speaker does not need to say them. Synonyms count. "
                        "For a question asking what something was compared to, an excerpt that gives the comparison is relevant. "
                        "If the content is different, imagined or explicitly attributed to the wrong named speaker, mark irrelevant. Return a JSON verdict."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "search request": question,
                            "actual speaker": DOC_ROLE.get(
                                row["speaker"].split(" ", 1)[0], row["speaker"]
                            ),
                            "selected words": quote,
                            "passage": row["text"],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "options": {
                "temperature": 0,
                "seed": 23,
                "num_ctx": 4096,
                "num_predict": 100,
            },
        },
    )
    return result.verdict == "relevant"


async def check_translation(
    question, queries, tool, http, host, model, instrument, steps, page
):
    speaker = named_speaker(question)
    steps.append(
        {
            "tool": tool,
            "argument": question,
            "output": {"detail": ", ".join(queries)},
        }
    )
    exact = []
    for query in queries:
        result = await instrument(
            "search_transcript", {"query": query, "speaker": speaker, "page": page}
        )
        matches = result["matches"]
        steps.append(
            {
                "tool": "search_transcript",
                "argument": query,
                "output": {
                    "detail": f"Выдано строк: {len(matches)}.",
                    "mode": result["mode"],
                },
            }
        )
        exact.extend(matches[:2])
    ranked = await instrument(
        "rank_transcript", {"question": question, "queries": queries, "page": page}
    )
    pool = {row["id"]: row for row in [*exact, *ranked["candidates"]]}
    rows = [
        r
        for r in pool.values()
        if not speaker or r["speaker"].split(" ", 1)[0] == speaker
    ]
    method = (
        "SQLite FTS5 и EmbeddingGemma"
        if ranked["mode"] == "fts+embeddinggemma"
        else "SQLite FTS5"
    )
    detail = (
        f"Чтение страницы {page}." if page is not None else f"Поиск по {method}."
    ) + f" Отобрано реплик: {len(rows)}."
    steps.append(
        {
            "tool": "rank_transcript",
            "argument": question,
            "output": {
                "detail": detail,
                "mode": ranked["mode"],
                "ids": [r["id"] for r in rows],
            },
        }
    )
    chosen, quote = await choose_source(question, rows, http, host, model, queries)
    hints = ranked.get("hints", {})
    allowed = {r["id"]: r for r in rows}
    anchored = [
        (allowed[hint["id"]], hint["quote"])
        for hint in hints.get("anchors", [])
        if hint["id"] in allowed
    ]
    trials = ([(chosen, quote)] if chosen else []) + anchored
    chosen, quote = None, ""
    inspected = set()
    review = []
    differences, other_events, best_counter = compare_quantities(
        question, queries, rows, page
    )
    parser_name = os.getenv("ARCHIVE_SPACY_MODEL", "")
    description = queries[0] if queries else question
    wanted = []
    permitted = transcript_movement.russian_directions(question)
    if trials and len(permitted) == 1:
        try:
            indexed = any(
                row["id"] in transcript_movement.source_index() for row, _ in trials
            )
            if indexed and parser_name:
                wanted = await asyncio.to_thread(
                    transcript_movement.requests, question, description, parser_name
                )
            elif indexed:
                wanted = await transcript_movement.read_request(
                    description, permitted, http, host, model
                )
        except (ImportError, OSError, ValueError, httpx.HTTPError):
            steps.append(
                {
                    "tool": "movement_check",
                    "argument": description,
                    "output": {
                        "detail": "Сопоставление направлений недоступно. Продолжается обычная проверка цитаты."
                    },
                }
            )
    if wanted:
        steps.append(
            {
                "tool": "movement_request",
                "argument": description,
                "output": {
                    "detail": "Проверяется направление движения предмета в исходной строке.",
                    "direction": wanted[0].direction,
                    "place": wanted[0].place,
                    "items": sorted(wanted[0].items),
                },
            }
        )
    for candidate, words in trials:
        if candidate["id"] in inspected:
            continue
        inspected.add(candidate["id"])
        admissible = matches_identifiers(
            question, candidate["text"]
        ) and supports_vocabulary(hints, candidate["text"])
        difference = differences.get(candidate["id"]) if admissible else None
        if wanted and admissible and not difference:
            movement = transcript_movement.compare_indexed(wanted, candidate)
            if movement:
                review.append({**candidate, "movement_difference": movement})
                steps.append(
                    {
                        "tool": "movement_check",
                        "argument": movement["request_words"],
                        "output": {
                            "detail": f"Стр. {candidate['page']}. В источнике движение описано словами «{movement['source_words']}».",
                            **movement,
                        },
                    }
                )
                continue
        supported = (
            admissible
            and not difference
            and candidate["id"] not in other_events
            and await supports_question(
                description, candidate, words, http, host, model
            )
        )
        steps.append(
            {
                "tool": "verify_transcript",
                "argument": words,
                "output": {
                    "detail": f"Стр. {candidate['page']}. Строка подтверждает описание."
                    if supported
                    else f"Стр. {candidate['page']}. Строка не подтверждает все существенные детали описания.",
                },
            }
        )
        if supported:
            chosen, quote = candidate, words
            break
        if (
            admissible
            and not difference
            and any(row["id"] == candidate["id"] for row, _ in anchored)
        ):
            review.append(candidate)
    if not chosen and best_counter is not None:
        counter = allowed[best_counter]
        if matches_identifiers(question, counter["text"]):
            review.append({**counter, "quantity_difference": differences[best_counter]})
    steps.append(
        {
            "tool": "select_transcript",
            "argument": quote,
            "output": {
                "detail": (
                    "Выбрана стр. " + str(chosen["page"])
                    if chosen
                    else "Подтвержденная цитата не выбрана."
                )
            },
        }
    )
    return PassageSearch(
        [chosen] if chosen else [],
        ", ".join(queries),
        ranked["mode"],
        quote,
        [] if chosen else review,
    )


async def search_description(question, http, host, model, instrument, steps, page=None):
    folder = os.environ.get("ARCHIVE_ARGOS_DIR", "")
    only = os.environ.get("ARCHIVE_ARGOS_MODE") == "only"

    async def try_argos():
        try:
            return await asyncio.to_thread(argos_translation.queries, question, folder)
        except (ImportError, OSError, RuntimeError, ValueError):
            steps.append(
                {
                    "tool": "argos_terms",
                    "argument": question,
                    "output": {
                        "detail": "Переводчик недоступен. Проверьте каталог ARCHIVE_ARGOS_DIR и установку CTranslate2 и SentencePiece."
                    },
                }
            )
            return []

    async def check(queries, tool):
        return await check_translation(
            question, queries, tool, http, host, model, instrument, steps, page
        )

    if folder and only and (queries := await try_argos()):
        return await check(queries, "argos_terms")
    queries = await translate(question, http, host, model)
    first = await check(queries, "transcript_terms")
    if not folder or only or first.matches or counterexample_in(first.review):
        return first
    alternative = await try_argos()
    if not alternative or alternative == queries:
        return first
    second = await check(alternative, "argos_terms")
    if second.matches or counterexample_in(second.review):
        return second
    combined = {r["id"]: r for r in [*first.review, *second.review]}
    return first._replace(review=list(combined.values()))


async def line_information(field, previous, instrument):
    line_id = previous.get("реплика_nasa")
    steps = []
    row = None
    if line_id:
        out = await instrument("read_transcript", {"line_id": line_id})
        steps.append(
            {"tool": "read_transcript", "argument": str(line_id), "output": out}
        )
        row = out["line"]
    if not row:
        text = "О какой реплике речь? Уточните ее время, говорящего или слова из стенограммы."
    elif field == "page":
        text = f"Эта реплика напечатана на странице {row['page']}."
    elif field == "time":
        text = (
            f"В стенограмме рядом с этой фразой стоит {row['get']} от старта миссии."
            if row["get"]
            else f"Исходная метка {row['printed_clock']} требует сверки со сканом."
        )
    else:
        code = row["speaker"].split(" ", 1)[0]
        text = f"На странице {row['page']} эта строка обозначена {row['speaker'] or 'как реплика без обозначения'}."
        if row["role"]:
            text += " Это " + row["role"] + "."
        if code not in {"CDR", "LMP", "CMP"}:
            text += " Личное имя в этой строке не указано."
    if row and field == "time" and (note := mission_time.context_note(row)):
        text += " " + note
    return {
        "steps": steps,
        "result": {
            "status": "answered" if row else "needs_input",
            "answer": text,
            "sources": [f"AP11-{row['page']}"] if row else [],
            "passages": [],
            "measurements": [],
            "transcript": {
                "matches": [{**row, "source_url": row_link(row)}] if row else [],
                "query": "",
                "metadata": field,
            },
        },
    }


async def timed_passages(question, address, page, instrument):
    query = literal_query(re.sub(r"\bGET\b", "", question, flags=re.IGNORECASE))
    data = await instrument(
        "search_transcript",
        {
            "clock": address,
            "query": query,
            "speaker": named_speaker(question),
            "page": page,
        },
    )
    clock = data.get("clock")
    invalid = data["mode"] == "invalid_mission_time"
    measured = False
    detail = data["detail"]
    if not invalid and mission_time.asks_difference(question):
        clock, difference = mission_time.measure_difference(clock, question)
        measured = clock is not None
        invalid = not measured
        detail = f"{difference} {detail}" if measured else difference
    matches = (
        [] if invalid else [{**r, "source_url": row_link(r)} for r in data["matches"]]
    )
    text = [detail]
    for row in matches:
        words = row["text"]
        if len(words) > 265:
            words = words[:260].rsplit(" ", 1)[0] + "…"
        label = row["role"] or row["speaker"] or "говорящий не обозначен"
        text.append(f"{row['get']} · стр. {row['page']} · {label}. «{words}»")
        if note := mission_time.context_note(row):
            text.append(note)
    mode = "invalid_mission_time" if invalid else data["mode"]
    return {
        "steps": [
            {
                "tool": "search_transcript",
                "argument": address,
                "output": {"mode": mode, "detail": detail},
            }
        ],
        "result": {
            "status": "needs_input"
            if invalid
            else "answered"
            if matches or measured
            else "no_evidence",
            "answer": "\n".join(text),
            "sources": list(dict.fromkeys(f"AP11-{r['page']}" for r in matches)),
            "passages": [],
            "measurements": [],
            "transcript": {
                "mode": mode,
                "matches": matches,
                "query": query,
                "clock": clock,
                "reference_id": matches[0]["id"] if len(matches) == 1 else 0,
            },
        },
    }


async def answer(question, previous, http, host, model, instrument):
    steps = []
    matches = []
    query = ""
    mode = ""
    quote = ""
    attribution = None
    review = []
    if cross_clock(question, previous):
        detail = (
            "Секунды WAV отсчитываются от начала конкретного файла. Стенограмма ведет часы от старта миссии. "
            "Для перевода нужна общая точка синхронизации на непрерывном участке. В приложенных оцифровках такая привязка не установлена."
        )
        steps.append(
            {
                "tool": "clock_reference",
                "argument": "WAV / Apollo 11 GET",
                "output": {"detail": detail},
            }
        )
        linked = []
        if line_id := previous.get("реплика_nasa"):
            out = await instrument("read_transcript", {"line_id": line_id})
            if row := out["line"]:
                linked = [{**row, "source_url": row_link(row)}]
                steps.append(
                    {"tool": "read_transcript", "argument": str(line_id), "output": out}
                )
                if row["get"]:
                    detail += f" У найденной ранее фразы в стенограмме стоит {row['get']} (стр. {row['page']})."
        return {
            "steps": steps,
            "result": {
                "status": "answered",
                "answer": detail,
                "sources": [f"AP11-{r['page']}" for r in linked],
                "passages": [],
                "measurements": [],
                "transcript": {
                    "matches": linked,
                    "query": "",
                    "alignment": "unavailable",
                },
            },
        }
    number = page_number(question)
    if address := mission_time.find_address(question):
        return await timed_passages(question, address, number, instrument)
    if number is not None:
        page = await instrument("read_transcript_page", {"number": number})
        steps.append(
            {"tool": "read_transcript_page", "argument": str(number), "output": page}
        )
        available = page["status"] == "available"
        if not available or opens_page(question):
            return {
                "steps": steps,
                "result": {
                    "status": "answered" if available else "no_evidence",
                    "answer": page["detail"],
                    "sources": [f"AP11-{number}"] if available else [],
                    "passages": [],
                    "measurements": [],
                    "transcript": {
                        "matches": [],
                        "query": "",
                        "page": number if available else None,
                    },
                },
            }
    offset = (
        direction(question) if previous.get("реплика_nasa") and number is None else 0
    )
    # Явная новая цитата начинает новый поиск, даже после вопроса о соседней реплике.
    literal = literal_query(question)
    field = requested_field(question)
    if (
        field
        and number is None
        and "реплика_nasa" in previous
        and not literal
        and not direction(question)
    ):
        return await line_information(field, previous, instrument)
    if (
        direction(question)
        and "реплика_nasa" in previous
        and not previous["реплика_nasa"]
        and number is None
        and not literal
    ):
        return {
            "steps": [],
            "result": {
                "status": "needs_input",
                "answer": "От какой реплики отсчитать? Напишите ее слова или сначала найдите ее в стенограмме.",
                "sources": [],
                "measurements": [],
                "passages": [],
                "transcript": {"matches": [], "query": ""},
            },
        }
    if literal:
        offset = 0
    if not literal and re.fullmatch(
        r"(?:покажи|открой|найди)?\s*(?:мне\s+)?(?:техническую\s+)?(?:стенограмму|расшифровку)\s*(?:nasa|наса|apollo[ -]*11|аполлон[ -]*11)[.!? ]*",
        question,
        re.IGNORECASE,
    ):
        return {
            "steps": steps,
            "result": {
                "status": "needs_input",
                "answer": "Какую фразу найти в стенограмме? Можно написать ее на английском или описать по-русски.",
                "sources": [],
                "passages": [],
                "measurements": [],
                "transcript": {"matches": [], "query": ""},
            },
        }
    if offset:
        line_id = previous["реплика_nasa"]
        out = await instrument(
            "read_transcript", {"line_id": line_id, "offset": offset}
        )
        steps.append(
            {
                "tool": "read_transcript",
                "argument": f"{line_id} {offset:+d}",
                "output": out,
            }
        )
        if out["line"]:
            matches = [out["line"]]
        empty = (
            "В этой стороне опубликованной стенограммы больше нет размеченных реплик."
        )
    elif literal:
        query = literal
        speaker = named_speaker(question)
        exact = bool(speaker) or any(mark in question for mark in ("«", '"', "“"))
        out = await instrument(
            "search_transcript",
            {"query": query, "speaker": speaker, "exact": exact, "page": number},
        )
        matches, mode = out["matches"], out["mode"]
        steps.append(
            {
                "tool": "search_transcript",
                "argument": query,
                "output": {
                    "detail": (
                        f"Проверена стр. {number}."
                        if number is not None
                        else f"Проверено страниц: {out['edition_pages']}."
                    )
                    + f" Совпадений: {len(matches)}."
                    + (f" Говорящий: {speaker}." if speaker else ""),
                    "mode": mode,
                },
            }
        )
        empty = "В размеченных репликах совпадений по этим словам не нашлось. Попробуйте другую формулировку."
        if speaker and not matches:
            out = await instrument(
                "search_transcript", {"query": query, "exact": True, "page": number}
            )
            steps.append(
                {
                    "tool": "search_transcript",
                    "argument": query,
                    "output": {
                        "detail": f"Дословная проверка по всем говорящим. Совпадений: {len(out['matches'])}."
                    },
                }
            )
            if out["matches"]:
                matches, mode = out["matches"], out["mode"]
                attribution = {
                    "asserted": speaker,
                    "actual": matches[0]["speaker"].split(" ", 1)[0],
                }
    else:
        matches, query, mode, quote, review = await search_description(
            question, http, host, model, instrument, steps, page=number
        )
        empty = "Среди найденных реплик не удалось подтвердить это описание."
    sources = []
    if matches:
        row = matches[0]
        role = row["role"] or row["speaker"] or "говорящий не обозначен"
        intro = (
            "Следующая размеченная реплика"
            if offset == 1
            else "Предыдущая размеченная реплика"
            if offset == -1
            else "Ближайшее совпадение"
        )
        spoken = row["text"]
        if quote and len(spoken) > 350:
            quoted_sentence = next(
                (
                    part
                    for part in re.split(r"(?<=[.!?])\s+", spoken)
                    if quote.casefold() in part.casefold()
                ),
                "",
            )
            spoken = quoted_sentence or spoken
        clock = (
            f"Время от старта миссии {row['get']}"
            if row["get"]
            else f"Требует сверки метка оригинала {row['printed_clock']}"
        )
        text = f"{intro} на странице {row['page']}. {clock}, {role}. «{spoken}»"
        if attribution:
            text = f"В строках с обозначением {attribution['asserted']} ({ROLES[attribution['asserted']]}) такой дословной цитаты не нашлось. На стр. {row['page']} ее произносит {role}. {clock}. «{spoken}»"
        if note := mission_time.context_note(row):
            text += " " + note
        sources = [f"AP11-{row['page']}"]
    else:
        text = (
            empty
            if number is None
            else f"На странице {number} подтвердить запрошенную фразу не удалось."
        )
    counterexample = counterexample_in(review)
    if counterexample:
        if movement := counterexample.get("movement_difference"):
            text += f" На стр. {counterexample['page']} стоит «{movement['source_words']}». В этой строке направление действия обратное тому, о котором вы спросили."
        else:
            difference = counterexample["quantity_difference"]
            text += f" На стр. {counterexample['page']} в источнике стоит «{difference['words']}». В вопросе указано другое количество ({difference['requested']})."
        sources = [f"AP11-{counterexample['page']}"]
        review = [row for row in review if row["id"] != counterexample["id"]]
    matches = [{**row, "source_url": row_link(row)} for row in matches]
    return {
        "steps": steps,
        "result": {
            "status": "answered" if matches else "no_evidence",
            "answer": text,
            "sources": sources,
            "measurements": [],
            "passages": [],
            "transcript": {
                "matches": matches,
                "query": query,
                "mode": mode,
                "quote": quote,
                **({"scope_page": number} if number is not None else {}),
                **({"attribution": attribution} if attribution else {}),
                **(
                    {
                        "counterexample": {
                            **counterexample,
                            "source_url": row_link(counterexample),
                        }
                    }
                    if counterexample
                    else {}
                ),
                **(
                    {
                        "review_candidates": [
                            {**candidate, "source_url": row_link(candidate)}
                            for candidate in review
                        ]
                    }
                    if review
                    else {}
                ),
            },
        },
    }
