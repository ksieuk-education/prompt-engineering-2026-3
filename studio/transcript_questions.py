"""Распознавание адреса страницы, авторства и уточнений о стенограмме."""

import re

from .mission_time import find_address
from .transcript import ROLES

NASA = r"\bnasa\b|\bнаса\b|(?:аполлон|apollo)[ -]*11"
DOCUMENT = r"стенограмм|расшифровк|транскрипт"


def requested_field(question):
    if re.search(
        r"\b(?:кто\s+(?:(?:именно|это|так)\s+){0,2}(?:сказал|говорил|говорит|произнес|произнёс)|кто это был|чья\s+(?:это\s+)?реплика|имя говорящего)",
        question,
        re.IGNORECASE,
    ):
        return "speaker"
    if re.fullmatch(
        r"\s*(?:а\s+)?(?:когда|во сколько)(?:\s+это\s+было)?[?.! ]*",
        question,
        re.IGNORECASE,
    ) or re.search(
        r"(?:какое время|когда|во сколько).*(?:этой фраз|эта фраз|этой реплик|эта реплик|по часам миссии)",
        question,
        re.IGNORECASE,
    ):
        return "time"
    if re.fullmatch(
        r"\s*(?:а\s+)?(?:на какой странице|какая страница)(?:\s+(?:это|она))?[?.! ]*",
        question,
        re.IGNORECASE,
    ):
        return "page"
    return ""


def named_speaker(question):
    names = {
        "CDR": r"армстронг\w*|armstrong",
        "LMP": r"олдрин\w*|алдрин\w*|aldrin",
        "CMP": r"коллинз\w*|коллинс\w*|collins",
        "CC": r"хьюстон\w*|houston",
    }
    speakers = []
    for code, name in names.items():
        person = r"(?:" + name + r")"
        by = (
            r"(?:слов[ао]|реплик[ауи]|цитат[ауые]|сказал|говорил|произнес|произнёс)\s+"
            + person
        )
        says = (
            person + r"\s+(?:сказал|говори|сравни|произнес|произнёс|сообщи|said|says)"
        )
        if re.search(by + "|" + says, question, re.IGNORECASE):
            speakers.append(code)
    return speakers[0] if len(speakers) == 1 else ""


def matches_identifiers(question, text):
    """Сохранять буквальные обозначения вроде USB-C, даже если перевод запроса их потерял."""
    tokens = re.findall(r"\b[A-Za-z]{1,8}[-‑–][A-Za-z0-9]{1,7}\b", question)
    for token in tokens:
        if re.fullmatch(NASA, re.sub(r"[‑–]", "-", token), re.IGNORECASE):
            continue
        parts = re.split(r"[-‑–]", token)
        if not re.search(
            r"\b" + r"[\s\-‑–]*".join(map(re.escape, parts)) + r"\b",
            text,
            re.IGNORECASE,
        ):
            return False
    acronyms = set(re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", question))
    context_labels = {"NASA", "GET", "WAV", "APOLLO", *ROLES}
    # В Wi-Fi и USB-C свое правило для вариантов с дефисом и без него.
    parts = {p for token in tokens for p in re.split(r"[-‑–]", token)}
    return all(
        re.search(r"\b" + re.escape(code) + r"\b", text, re.IGNORECASE)
        for code in acronyms - context_labels - parts
    )


def direction(question):
    if re.search(
        r"\b(?:следующ|дальше|затем|потом|после этого|ответил|ответили)",
        question,
        re.IGNORECASE,
    ):
        return 1
    if re.search(
        r"\b(?:предыдущ|перед (?:этой|этим)|до этого|до нее|до неё)",
        question,
        re.IGNORECASE,
    ):
        return -1
    return 0


PAGE_ADDRESS = re.compile(
    r"\b(?:страниц[а-яё]*|стр\.)\s*№?\s*(\d{1,4})\b", re.IGNORECASE
)


def opens_page(question):
    residual = PAGE_ADDRESS.sub(" ", question)
    residual = re.sub(
        NASA + "|(?:" + DOCUMENT + r")[а-яё]*", " ", residual, flags=re.IGNORECASE
    )
    words = re.findall(r"[а-яёa-z]+", residual.lower())
    return all(
        w
        in {
            "открой",
            "открыть",
            "покажи",
            "показать",
            "найди",
            "перейди",
            "страницу",
            "на",
            "из",
            "в",
            "мне",
            "пожалуйста",
            "а",
            "теперь",
            "технической",
            "техническую",
        }
        for w in words
    )


def page_number(question):
    if found := PAGE_ADDRESS.search(question):
        return int(found[1])
    return None


def cross_clock(question, previous):
    audio = re.search(
        r"\bwav\b|аудиофайл|секунд[а-яё]* (?:коротк|длинн|расширен)|счетчик[а-яё]* (?:файла|плеера)",
        question,
        re.IGNORECASE,
    )
    mission = re.search(
        r"(?:от |со )?старта миссии|час[а-яё]* миссии|времен[а-яё]* миссии|стенограмм[а-яё]*|\bget\b",
        question,
        re.IGNORECASE,
    )
    return bool(
        audio
        and mission
        and (
            re.search(NASA, question, re.IGNORECASE)
            or "реплика_nasa" in previous
            or previous.get("открытая_сверка")
        )
    )


def requested(question, previous):
    named = re.search(NASA, question, re.IGNORECASE)
    document = re.search(DOCUMENT, question, re.IGNORECASE)
    if find_address(question) and (
        re.search(
            r"\bGET\b|(?:врем\w*|час\w*) миссии|старта миссии", question, re.IGNORECASE
        )
        or (
            (named or "реплика_nasa" in previous)
            and not re.search(r"катушк|эфирн|\bwav\b", question, re.IGNORECASE)
        )
    ):
        return True
    if (named and (document or page_number(question) is not None)) or cross_clock(
        question, previous
    ):
        return True
    if previous.get("открытая_сверка") and document:
        return True
    return (
        "реплика_nasa" in previous
        and (
            bool(document)
            or page_number(question) is not None
            or bool(requested_field(question))
            or bool(direction(question))
            or bool(
                re.match(
                    r"\s*(?:найди|поищи|а про|теперь про|[«\"]|[a-z])",
                    question,
                    re.IGNORECASE,
                )
            )
        )
        and not re.search(
            r"катушк|позывн|эфирн|по (?:волне|спектру)", question, re.IGNORECASE
        )
    )


def literal_query(question):
    for phrase in re.findall(r"[«\"“](.+?)[»\"”]", question):
        if re.search("[a-z]", phrase, re.IGNORECASE) and not re.search(
            "[а-яё]", phrase, re.IGNORECASE
        ):
            return phrase.strip()
    clean = re.sub(NASA, " ", question, flags=re.IGNORECASE)
    chunks = re.findall(r"[a-z]+(?:[ '\-]+[a-z]+)*", clean, re.IGNORECASE | re.ASCII)
    longest = max((s.strip() for s in chunks), key=len, default="")
    # Обозначение в русском описании действия остается условием поиска по смыслу.
    technical_name = "-" in longest or bool(
        re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", longest)
    )
    named_term = (
        re.search(
            r"\b(?:слов[оау]|сокращение|обозначение|аббревиатур[ау])\s+"
            + re.escape(longest)
            + r"\b",
            clean,
            re.IGNORECASE,
        )
        if longest
        else False
    )
    if (
        technical_name
        and not named_term
        and len(re.findall(r"[а-яё]{3,}", clean, re.IGNORECASE)) > 3
    ):
        return ""
    return longest
