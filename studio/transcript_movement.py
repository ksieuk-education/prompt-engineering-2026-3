"""Сверка направления движения предмета по синтаксическому разбору английской строки."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from typing import Literal

from pydantic import BaseModel, Field

from .archive import ROOT
from .ollama import structured
from .transcript_evidence import ENGLISH

# Один и тот же глагол может обозначать разные направления. Направление задает предлог при месте.
MOVING = {
    "put",
    "place",
    "insert",
    "stick",
    "store",
    "stow",
    "tuck",
    "slide",
    "move",
    "transfer",
    "drop",
    "pack",
    "load",
    "return",
    "remove",
    "retrieve",
    "take",
    "pull",
    "withdraw",
    "extract",
    "lift",
    "get",
    "bring",
    "deposit",
    "pick",
    "shift",
    "shove",
}
QUERY_VERBS = set(
    ENGLISH.stemWords(
        sorted(
            MOVING
            | {
                "carry",
                "transport",
                "took",
                "taken",
                "got",
                "gotten",
                "brought",
                "stuck",
                "withdrawn",
                "slid",
            }
        )
    )
)
GENERIC_ITEMS = {"thing", "object", "item", "stuff", "something", "gear"}
PARSER_LOCK = Lock()
RUSSIAN = {
    "into": re.compile(
        r"\b(?:полож|помест|засун|встав|влож|класть|клад[уеи]|улож|укладыв)",
        re.IGNORECASE,
    ),
    "from": re.compile(
        r"\b(?:выну|вынул|вынем|выним|извле[чк]|достать|доста[лню]|вытащ|вытаск|вытян)",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class Transfer:
    direction: str
    place: str
    modifiers: frozenset[str]
    items: frozenset[str]
    words: str


@lru_cache(maxsize=1)
def pipeline(model):
    import spacy

    return spacy.load(model, exclude=["ner"])


def russian_directions(question):
    if re.search(r"\b(?:не|никогда)\b", question, re.IGNORECASE):
        return set()
    return {
        direction for direction, pattern in RUSSIAN.items() if pattern.search(question)
    }


def events(doc):
    output = []
    for target in doc:
        if target.dep_ != "pobj" or target.pos_ not in {"NOUN", "PROPN"}:
            continue
        prep = target.head
        if prep.lower_ == "of" and prep.head.lower_ == "out":
            prep = prep.head
        if prep.lower_ in {"in", "into", "inside"}:
            direction = "into"
        elif prep.lower_ in {"from", "out"}:
            direction = "from"
        else:
            continue
        verb = prep.head
        # Некоторые сочетания типа «place the cable in the case» парсер присоединяет к прямому дополнению.
        if verb.dep_ == "dobj":
            verb = verb.head
        if (
            verb.pos_ != "VERB"
            or verb.lemma_ not in MOVING
            or any(child.dep_ == "neg" for child in verb.children)
        ):
            continue
        objects = [
            child for child in verb.children if child.dep_ in {"dobj", "nsubjpass"}
        ]
        items = frozenset(
            part.lemma_.lower()
            for obj in objects
            for part in (obj, *obj.conjuncts)
            if part.pos_ in {"NOUN", "PROPN"}
            and part.lemma_.lower() not in GENERIC_ITEMS
        )
        modifiers = frozenset(
            child.lemma_.lower()
            for child in target.children
            if child.dep_ in {"compound", "amod", "nummod"}
        )
        start, stop = sorted((verb.i, target.i))
        output.append(
            Transfer(
                direction,
                target.lemma_.lower(),
                modifiers,
                items,
                doc[start : stop + 1].text,
            )
        )
    return output


def same_transfer(a, b):
    return (
        a.place == b.place
        and (a.modifiers <= b.modifiers or b.modifiers <= a.modifiers)
        and (not a.items or not b.items or not a.items.isdisjoint(b.items))
    )


def difference(wanted, observed):
    for request in wanted:
        comparable = [
            movement for movement in observed if same_transfer(request, movement)
        ]
        if comparable and all(m.direction != request.direction for m in comparable):
            hit = comparable[0]
            return {
                "requested": request.direction,
                "observed": hit.direction,
                "place": request.place,
                "request_words": request.words,
                "source_words": hit.words,
            }
    return None


def parse(text, model):
    with PARSER_LOCK:
        return events(pipeline(model)(text))


def requests(question, description, model):
    permitted = russian_directions(question)
    if not permitted or not model:
        return []
    return [
        event for event in parse(description, model) if event.direction in permitted
    ]


@lru_cache(maxsize=1)
def source_index():
    from .semantic import corpus_digest

    data = json.loads((ROOT / "data/field/transcript-movements.json").read_text())
    if data["corpus_sha256"] != corpus_digest():
        raise ValueError("Индекс действий относится к другой редакции стенограммы.")
    audit = json.loads(
        (ROOT / "data/field/transcript-transfer-review.json").read_text()
    )
    if audit["corpus_sha256"] != data["corpus_sha256"]:
        raise ValueError("Сверка цитат относится к другой редакции.")
    approved = {}
    for item in audit["accepted"]:
        matching = [
            e
            for e in data["actions"].get(str(item["id"]), [])
            if e["words"] == item["words"]
        ]
        if len(matching) != 1:
            raise ValueError("Проверенная фраза отсутствует в синтаксическом разборе.")
        e = matching[0]
        approved.setdefault(item["id"], []).append(
            Transfer(
                e["direction"],
                e["place"],
                frozenset(e["modifiers"]),
                frozenset(e["items"]),
                e["words"],
            )
        )
    return approved


class RequestedTransfer(BaseModel):
    verb: str = Field(max_length=45)
    item: str = Field(max_length=80)
    place: str = Field(max_length=80)
    direction: Literal["into", "from", "unclear"]


IGNORE = {
    "a",
    "an",
    "the",
    "his",
    "her",
    "their",
    "its",
    "my",
    "your",
    "our",
    "this",
    "that",
    "it",
    *GENERIC_ITEMS,
}


def question_transfer(result, description, permitted):
    def words(text):
        return re.findall(r"[a-z0-9]+", text.lower())

    sentence = " " + " ".join(words(description)) + " "
    if result.direction not in permitted or not result.verb or not result.place:
        return []
    if not QUERY_VERBS.intersection(ENGLISH.stemWords(words(result.verb))):
        return []
    for field in (result.verb, result.place, result.item):
        if field and " " + " ".join(words(field)) + " " not in sentence:
            return []
    # В «the drawer under the table» предмет кладут в ящик. Стол уточняет, какой это ящик.
    main_place = re.split(
        r"\b(?:under|over|near|behind|beside|underneath|next to|on|in|of|with)\b",
        result.place,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    place = [word for word in words(main_place) if word not in IGNORE]
    if not place:
        return []
    prefix = "from|out of" if result.direction == "from" else "into|inside|in"
    # Модель назвала направление. В самом переводе перед местом должен быть подходящий предлог.
    context = rf"\b(?:{prefix})\s+(?:[a-z0-9]+\s+){{0,4}}{re.escape(place[-1])}\b"
    if not re.search(context, sentence):
        return []
    items = frozenset(w for w in words(result.item) if w not in IGNORE)
    return [
        Transfer(
            result.direction,
            place[-1],
            frozenset(place[:-1]),
            items,
            description,
        )
    ]


async def read_request(description, permitted, http, host, model):
    reply = await structured(
        http,
        host + "/api/chat",
        expected=RequestedTransfer,
        retry_limit=850,
        json={
            "model": model,
            "stream": False,
            "think": False,
            "format": RequestedTransfer.model_json_schema(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Identify one physical transfer requested in the supplied search description. "
                        "Copy the exact verb, item being moved, and target container or location, in its printed word order. "
                        "Use into if the item is placed inside that location, from if it is removed from that location. "
                        "The search itself is not a movement. If no single such movement is requested, use unclear and empty strings. "
                        "Keep material modifiers on the item and location. Use an empty item if it is unspecified. Return JSON."
                    ),
                },
                {"role": "user", "content": description},
            ],
            "options": {
                "temperature": 0,
                "seed": 23,
                "num_ctx": 2048,
                "num_predict": 150,
            },
        },
    )
    return question_transfer(reply, description, permitted)


def stemmed(event):
    return Transfer(
        event.direction,
        ENGLISH.stemWord(event.place),
        frozenset(ENGLISH.stemWords(sorted(event.modifiers))),
        frozenset(ENGLISH.stemWords(sorted(event.items))),
        event.words,
    )


def compare_indexed(wanted, candidate):
    source = [
        stemmed(event)
        for event in source_index().get(candidate["id"], [])
        if event.words in candidate["text"]
    ]
    return difference([stemmed(event) for event in wanted], source)
