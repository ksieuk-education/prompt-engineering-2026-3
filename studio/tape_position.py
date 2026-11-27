"""Уточнение звука и шкалы времени при чтении описи одной катушки."""

import re

from .archive import terms
from .questions import marker_scores
from .transcript_questions import NASA

COUNTER = re.compile(
    r"(?:(?:на|с)\s+какой\s+(?:именно\s+)?(?:секунде|секунды|отметке|позиции)|"
    r"\bтаймкод\w*|где\s+на\s+(?:ленте|копии|катушке)|"
    r"(?:позиц\w*|отметк\w*)\s+(?:на\s+|по\s+)?(?:сч[её]тчик|лент|копи))",
    re.IGNORECASE,
)
AIR = re.compile(r"эфир\w*|по часам", re.IGNORECASE)
OTHER_TASK = re.compile(
    r"похож|повтор|спектр|стенограмм|между|через сколько|сколько прошло|почему|причин",
    re.IGNORECASE,
)
SAME = re.compile(
    r"\b(?:этот же|эта же|это же|этого же|тот же|он|она|его|ее|её)\b", re.IGNORECASE
)
CONNECTORS = set(terms("а теперь тогда еще насчет пожалуйста покажи"))


def request(question, case, previous):
    if re.search(NASA, question, re.IGNORECASE) or OTHER_TASK.search(question):
        return None
    last = previous.get("метка_копии", {})
    counter = COUNTER.search(question)
    if not last and not counter:
        return None
    scores = marker_scores(case, question)
    highest = max(scores.values(), default=0)
    choices = [key for key, score in scores.items() if score and score == highest]
    marked_words = {word for m in case["markers"] for word in terms(m["label"])}
    short = bool(choices) and set(terms(question)) <= marked_words | CONNECTORS
    copy_named = re.search(
        r"копи|лент|катушк|пл[её]нк|запис|файл|фонограмм|сч[её]тчик",
        question,
        re.IGNORECASE,
    )
    if counter and (copy_named or choices or last) and not AIR.search(question):
        basis = "tape"
    elif (
        last
        and AIR.search(question)
        and (
            SAME.search(question) or short or not choices and len(terms(question)) <= 2
        )
    ):
        basis = "air"
    elif last and short:
        basis = last["basis"]
    else:
        return None
    if (
        last.get("marker") in scores
        and SAME.search(question)
        and last["marker"] in choices
    ) or (
        not choices and last.get("marker") and (SAME.search(question) or basis == "air")
    ):
        choices = [last["marker"]]
    return {"basis": basis, "choices": choices}
