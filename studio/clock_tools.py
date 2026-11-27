"""Измерения времени. В расчете участвуют только метки и документы текущего дела."""

from typing import Literal

from .archive import CASES

ClockBasis = Literal["air", "tape"]


def seconds(wall: str) -> int:
    hours, minutes, secs = map(int, wall.split(":"))
    return hours * 3600 + minutes * 60 + secs


def timecode(total: int) -> str:
    total %= 86400
    return f"{total // 3600:02}:{total % 3600 // 60:02}:{total % 60:02}"


def elapsed(value: int) -> str:
    return f"{value // 60:02}:{value % 60:02}"


def tape_span(case_id: str, first: str, second: str) -> dict:
    case = CASES[case_id]
    markers = {m["id"]: m for m in case["markers"]}
    result = {
        "kind": "tape_span",
        "label": "Интервал по счетчику ленты",
        "sources": [case["tape_source"]],
    }
    if first not in markers or second not in markers or first == second:
        return {
            **result,
            "status": "insufficient",
            "value": "Нужны две метки",
            "detail": "Укажите два разных звука, между которыми нужно измерить время на ленте.",
        }
    a, b = sorted((markers[first], markers[second]), key=lambda m: m["second"])
    duration = b["second"] - a["second"]
    return {
        **result,
        "status": "verified",
        "from_marker": a["id"],
        "to_marker": b["id"],
        "tape_seconds": duration,
        "value": f"{duration} с",
        "detail": f"По счетчику между метками «{a['label']}» ({elapsed(a['second'])}) и «{b['label']}» ({elapsed(b['second'])}) прошло {duration} с.",
    }


def locate_marker(case_id: str, marker: str = "", basis: ClockBasis = "air") -> dict:
    case = CASES[case_id]
    marks = {m["id"]: m for m in case["markers"]}
    selected = marks.get(marker or case["target"])
    if selected is None:
        return {"status": "unknown_marker", "available": list(marks), "sources": []}
    local = selected["second"]
    if basis == "tape":
        return {
            "kind": "tape_position",
            "case_id": case_id,
            "marker": selected["id"],
            "label": selected["label"],
            "second": local,
            "tape": elapsed(local),
            "status": "verified",
            "value": elapsed(local),
            "sources": [case["tape_source"]],
            "detail": f"Метка «{selected['label']}» стоит на {elapsed(local)} от начала копии.",
        }
    sources = [case["tape_source"], case["clock_source"]]
    plan = case["planned"]
    compare_plan = plan and selected["id"] == plan["marker"]
    if compare_plan:
        sources.append(plan["source"])
    evidence = {
        "marker": selected["id"],
        "label": selected["label"],
        "tape": elapsed(local),
        "sources": sources,
    }
    if compare_plan:
        evidence["planned"] = plan["wall"]
    anchors = case["anchors"]
    if not anchors:
        return {
            **evidence,
            "status": "insufficient",
            "value": "Нет привязки к эфиру",
            "detail": f"На ленте {elapsed(local)}. Нужна общая метка с известным эфирным временем.",
        }
    offsets = {
        (seconds(a["wall"]) - marks[a["marker"]]["second"]) % 86400 for a in anchors
    }
    exact = next((a for a in anchors if a["marker"] == selected["id"]), None)
    if len(offsets) > 1 and not exact:
        return {
            **evidence,
            "status": "insufficient",
            "value": "Неизвестная поправка",
            "detail": "Опоры дают разные смещения. Время внутренней метки однозначно не восстанавливается.",
        }
    anchor = exact or anchors[0]
    travel = local - marks[anchor["marker"]]["second"]
    actual = (seconds(anchor["wall"]) + travel) % 86400
    data = {
        **evidence,
        "status": "verified",
        "value": timecode(actual),
        "anchor": anchor["wall"],
        "anchor_tape": elapsed(marks[anchor["marker"]]["second"]),
        "travel_seconds": travel,
        "detail": f"Опора {anchor['wall']} и сдвиг по ленте {travel:+d} с.",
    }
    if compare_plan:
        shift = (actual - seconds(plan["wall"]) + 43200) % 86400 - 43200
        data["shift_seconds"] = shift
        data["detail"] += f" Отклонение от сетки {shift:+d} с."
    return data


def compare_span(case_id: str) -> dict:
    case = CASES[case_id]
    refs = [case["clock_source"], case["tape_source"]]
    anchors = case["anchors"]
    if len(anchors) < 2:
        return {
            "status": "insufficient",
            "value": "Недостаточно опор",
            "sources": refs,
            "detail": "Для сравнения нужны две метки с известным эфирным временем.",
        }
    marks = {m["id"]: m["second"] for m in case["markers"]}
    ordered = sorted(anchors, key=lambda a: marks[a["marker"]])
    first, last = ordered[0], ordered[-1]
    airtime = (seconds(last["wall"]) - seconds(first["wall"])) % 86400
    taped = marks[last["marker"]] - marks[first["marker"]]
    delta = airtime - taped
    return {
        "status": "verified",
        "value": f"{abs(delta)} с",
        "air_seconds": airtime,
        "tape_seconds": taped,
        "missing_seconds": delta,
        "sources": refs,
        "detail": f"В эфире {airtime} с, на копии {taped} с. Разность {delta:+d} с.",
    }
