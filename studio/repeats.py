"""Сверка эфирных часов двух верифицированных по WAV фрагментов."""

import re
from math import isfinite

from .archive import CASES
from .audio_search import WINDOW, Scope, match_sound, tape_position
from .clock_tools import locate_marker

TOLERANCE = 0.04


def clock_for_position(case_id, second):
    case = CASES[case_id]
    markers = [m for m in case["markers"] if abs(m["second"] - second) <= TOLERANCE]
    clock = (
        locate_marker(case_id, markers[0]["id"])
        if len(markers) == 1
        else {
            "status": "unlabelled",
            "value": "Нет опознанной временной метки",
            "sources": [case["tape_source"]],
        }
    )
    return {"case_id": case_id, "code": case["code"], "second": second, "clock": clock}


def describe_position(position):
    clock = position["clock"]
    name = f"{position['code']} на {tape_position(position['second'])} от начала файла"
    if clock["status"] == "verified":
        return f"{name} соответствует {clock['value']} по эфирным часам."
    if clock["status"] == "unlabelled":
        return f"{name}. В описи на этой позиции нет однозначно опознанной метки."
    reason = clock["detail"].removeprefix(f"На ленте {clock['tape']}. ")
    return f"{name}. Эфирное время не установлено. {reason}"


def compare_repeat_clocks(
    case_id: str,
    start_seconds: float,
    scope: Scope = "archive",
    candidate_case: str = "",
    candidate_second: float | None = None,
    other_tape: bool = False,
):
    if candidate_second is not None and (
        not isfinite(candidate_second) or candidate_second < 0
    ):
        raise ValueError("Позиция повтора должна быть неотрицательным числом.")
    search = match_sound(case_id, start_seconds, scope)
    base = {
        "kind": "repeat_clocks",
        "label": "Эфирные часы двух фрагментов",
        "sources": [],
        "case_id": case_id,
        "reference_second": start_seconds,
        "scope": scope,
        "window_seconds": WINDOW,
    }
    hits = search["matches"]
    if not hits:
        return {
            **base,
            "status": search["status"],
            "value": "Нет найденного повтора",
            "detail": search["detail"],
        }
    if other_tape and all(hit["case_id"] == case_id for hit in hits):
        return {
            **base,
            "status": "no_other_tape",
            "value": "Повтор только на исходной катушке",
            "detail": "По звуку найден повтор внутри исходной катушки. Подтвержденного совпадения на другой катушке нет.",
        }
    eligible = [
        h
        for h in hits
        if (not other_tape or h["case_id"] != case_id)
        and (not candidate_case or h["case_id"] == candidate_case)
        and (
            candidate_second is None or abs(h["second"] - candidate_second) <= TOLERANCE
        )
    ]
    if len(eligible) != 1:
        options = eligible or hits
        wording = (
            "Какой из повторов проверить?"
            if eligible
            else "Указанная позиция отсутствует среди найденных повторов."
        )
        choices = ", ".join(
            h["code"] + " на " + tape_position(h["second"]) for h in options
        )
        return {
            **base,
            "status": "choose" if eligible else "not_listed",
            "value": "Нужно выбрать фрагмент",
            "detail": wording + " Доступны " + choices + ".",
            "options": options,
        }
    hit = eligible[0]
    source = clock_for_position(case_id, start_seconds)
    target = clock_for_position(hit["case_id"], hit["second"])
    sources = list(
        dict.fromkeys([*source["clock"]["sources"], *target["clock"]["sources"]])
    )
    detail = (
        "Найденный повтор — "
        + describe_position(target)
        + " Исходный образец — "
        + describe_position(source)
    )
    provenance = "Сходства звука недостаточно для вывода об одном и том же эфире. Для этого нужна документальная связь между записями."
    return {
        **base,
        "status": "compared",
        "value": "Сверены две позиции",
        "detail": detail,
        "source": source,
        "target": target,
        "score": hit["score"],
        "sources": sources,
        "provenance": provenance,
    }


def remember(measurements):
    for m in measurements:
        if m.get("kind") in {"audio", "repeat_clocks"}:
            result = {
                "case_id": m["case_id"],
                "start_seconds": m["reference_second"],
                "scope": m["scope"],
            }
            if m.get("target"):
                result.update(
                    candidate_case=m["target"]["case_id"],
                    candidate_second=m["target"]["second"],
                )
            return result
    return None


def followup(question, memory):
    if not memory:
        return None
    text = question.lower().replace("ё", "е")
    identity = bool(
        re.search(
            r"(?:один|тот|одного|того) и тот же эфир|одного и того же эфир|общ\w* (?:эфир|происхожд)|происхожд|одна и та же передача",
            text,
        )
    )
    clock = bool(
        re.search(
            r"эфирн\w* (?:врем|час)|во сколько|время (?:эфира|выхода)|когда .*эфир",
            text,
        )
    )
    reference = bool(
        re.search(
            r"найденн|совпадени|повтор|исходн\w* (?:образц|фрагмент|удар)|друг\w* катушк",
            text,
        )
    )
    selection = re.search(r"фн[ -]?(\d{3})", text)
    if not (identity or clock and reference or selection and len(text.split()) <= 5):
        return None
    args = dict(memory)
    if selection:
        args["candidate_case"] = next(
            (
                key
                for key, c in CASES.items()
                if c["code"].lower().endswith(selection[1])
            ),
            "unknown",
        )
        args.pop("candidate_second", None)
    position = re.search(r"(?<![\d:])(\d{1,2}):([0-5]\d(?:[.,]\d+)?)(?![\d:])", text)
    if position:
        args["candidate_second"] = int(position[1]) * 60 + float(
            position[2].replace(",", ".")
        )
    if re.search(r"друг\w* катушк", text):
        args["other_tape"] = True
    return args, identity
