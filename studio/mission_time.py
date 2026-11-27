"""Поиск по напечатанным меткам времени от старта миссии Apollo 11."""

import json
import re
from functools import lru_cache

from .archive import ROOT

STAMP = r"[0-9]{1,4}:[0-9]{1,2}:[0-9]{1,2}"
ADDRESS = re.compile(r"(?<![0-9:])" + STAMP + r"(?![0-9:])")
MARK = rf"(?:GET\s*)?{STAMP}"
POINTS = r"(?:,|;|&|или|и|and|or)"
RANGE = r"(?:[-–—…]|\.{2,3}|до|по|to)"
DIRECT = re.compile(
    rf"\s*{MARK}(?:\s*(?:{POINTS}|{RANGE})\s*{MARK})?\s*", re.IGNORECASE
)
SEPARATE = re.compile(rf"\s*{MARK}\s*{POINTS}\s*{MARK}\s*", re.IGNORECASE)
MAX_SHOWN = 8


def elapsed(stamp):
    day, hour, minute, second = map(int, stamp.split())
    if day > 8 or hour >= 24 or minute >= 60 or second >= 60:
        return None
    return f"{day * 24 + hour:03}:{minute:02}:{second:02}"


@lru_cache(maxsize=1)
def compared_edition():
    return json.loads((ROOT / "data/field/transcript-clock-editions.json").read_text())


def edition_note(entry):
    return (
        f"В HTML стоит {entry['html_stamp']} ({elapsed(entry['html_stamp'])}). "
        f"На скане напечатано {entry['scan_stamp']} ({elapsed(entry['scan_stamp'])} от старта миссии)."
    )


def apply_scan_readings(rows):
    for entry in compared_edition()["verified"]:
        row = rows[entry["id"] - 1]
        if row["page"] != entry["page"] or row["get"] != elapsed(entry["html_stamp"]):
            raise ValueError(f"Запись сверки не относится к строке {row['id']}.")
        row["html_get"] = row["get"]
        row["get"] = elapsed(entry["scan_stamp"])
        row["edition_note"] = edition_note(entry)


def scan_page(number):
    edition = compared_edition()
    if number not in edition["scan_pages"]:
        return {}
    physical = edition["scan_pages"].index(number) + 1
    notes = [edition_note(e) for e in edition["verified"] if e["page"] == number]
    return {
        "source": f"{edition['source']}#page={number + 2}",
        "local_scan": f"{edition['local_scan']}#page={physical}",
        "edition_note": " ".join(notes) + " Ниже приведен текст HTML.",
    }


def asks_difference(question):
    return bool(
        re.search(
            r"\b(?:разниц\w*|разност\w*)\s+(?:между|по\s+часам|во?\s+времени|в\s+секундах|меток)|"
            r"\bсколько\b.{0,60}\b(?:прошло|проходит|разделя\w*)|\bсколько\s+(?:секунд|минут|часов|времени)\s+(?:между|от)|"
            r"\b(?:time difference|elapsed time)\b",
            question,
            re.IGNORECASE,
        )
    )


def find_address(question):
    marks = list(ADDRESS.finditer(question))
    if len(marks) != 2:
        return ", ".join(m.group() for m in marks)
    first, last = marks
    between = question[first.end() : last.start()]
    # «Между X и Y» задает интервал. «На X и на Y» просит только его концы.
    listed = re.search(r"[,;]|\b(?:и|или|and|or)\b", between, re.IGNORECASE)
    range_word = re.search(
        r"\b(?:между|between)\b", question[: first.start()], re.IGNORECASE
    )
    separator = (
        ", " if asks_difference(question) or (listed and not range_word) else "–"
    )
    return first.group() + separator + last.group()


def measure_difference(clock, question):
    stamps = clock.get("stamps", [])
    if len(stamps) != 2:
        return None, "Для расчета укажите две метки времени от старта миссии."
    start, end = stamps
    first, last = ADDRESS.finditer(question)
    connector = question[first.end() : last.start()]
    if start > end and re.search(r"\b(?:до|по|to)\b", connector, re.IGNORECASE):
        return None, "Конец интервала предшествует началу. Проверьте порядок меток."

    def seconds(stamp):
        h, m, s = map(int, stamp.split(":"))
        return h * 3600 + m * 60 + s

    delta = abs(seconds(end) - seconds(start))
    clock = {**clock, "kind": "elapsed", "seconds": delta}
    return (
        clock,
        f"Разница показаний часов миссии {start} и {end} составляет {delta} с.",
    )


def normalized(stamp):
    hours, minutes, seconds = stamp.split(":")
    if len(hours) > 3 or len(minutes) != 2 or len(seconds) != 2:
        return None
    if int(minutes) >= 60 or int(seconds) >= 60:
        return None
    return f"{int(hours):03}:{minutes}:{seconds}"


def mark_discontinuities(rows):
    ordered = sorted(rows, key=lambda row: (row["page"], row["id"]))
    for before, row, after in zip(ordered, ordered[1:], ordered[2:]):
        first, current, last = (r["get"] for r in (before, row, after))
        if (
            before["page"] == row["page"] == after["page"]
            and first
            and current
            and last
            and first <= last
            and not first <= current <= last
        ):
            row["clock_neighbors"] = [first, last]


def context_note(row):
    notes = [row["edition_note"]] if row.get("edition_note") else []
    if times := row.get("clock_neighbors"):
        notes.append(
            f"На этой странице соседние строки имеют метки {times[0]} и {times[1]}. Порядок расходится с указанным временем."
        )
    return " ".join(notes)


def words(text):
    return " " + " ".join(re.findall("[a-z0-9]+", text.lower())) + " "


def search(rows, address, *, phrase="", speaker="", page=None):
    found = ADDRESS.findall(address)
    stamps = [normalized(stamp) for stamp in found]
    invalid = {
        "mode": "invalid_mission_time",
        "matches": [],
        "detail": "Введите метку в формате ЧЧЧ:ММ:СС или две метки по порядку. Минуты и секунды должны быть от 00 до 59.",
    }
    if not DIRECT.fullmatch(address) or not stamps or not all(stamps):
        return invalid
    start, end = stamps[0], stamps[-1]
    points = bool(SEPARATE.fullmatch(address))
    if not points and start > end:
        return {
            **invalid,
            "detail": "Конец интервала предшествует началу. Укажите сначала более раннюю метку миссии.",
        }
    needle = words(phrase) if phrase else ""
    hits = []
    counts = dict.fromkeys(stamps, 0)
    for row in rows:
        readings = (row["get"], row.get("html_get"))
        if points:
            selected = [stamp for stamp in counts if stamp in readings]
            if not selected:
                continue
            key = stamps.index(selected[0])
        else:
            key = next(
                (stamp for stamp in readings if stamp and start <= stamp <= end), None
            )
            if key is None:
                continue
        if page is not None and row["page"] != page:
            continue
        if speaker and row["speaker"].split(" ", 1)[0] != speaker:
            continue
        if not needle or needle in words(row["text"]):
            hits.append((key, row["page"], row["id"], row))
            if points:
                for stamp in selected:
                    counts[stamp] += 1
    hits.sort(key=lambda item: item[:3])
    matches = [item[3] for item in hits]
    scope = f"на странице {page}" if page is not None else "в стенограмме"
    span = start if start == end else f"{start}–{end}"
    clock = {"start": start, "end": end, "total": len(matches)}
    if points:
        clock.update(kind="points", stamps=stamps, counts=counts)
        summary = ", ".join(f"{stamp} — {count}" for stamp, count in counts.items())
        detail = f"Начала реплик {scope} по отдельным меткам. {summary}."
        if 0 in counts.values():
            detail += " Отсутствие метки начала не доказывает тишину в эфире."
    elif not matches:
        detail = f"По времени миссии {span} {scope} нет начала размеченной реплики"
        if phrase or speaker:
            detail += " с указанными словами или говорящим"
        detail += ". По меткам начала нельзя судить о тишине в эфире."
    else:
        detail = f"Запрошенное время от старта миссии {span}. Число подходящих строк {scope} — {len(matches)}."
    if len(matches) > MAX_SHOWN:
        detail += f" Показаны первые {MAX_SHOWN}. Уточните время или страницу, чтобы увидеть остальные."
    return {
        "mode": "mission_time",
        "matches": matches[:MAX_SHOWN],
        "clock": clock,
        "detail": detail,
    }
