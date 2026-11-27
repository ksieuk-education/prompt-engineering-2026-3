"""Определение предмета вопроса и названных звуковых меток."""

import re

from .archive import terms


def public_request(
    question: str, previous: str = "", remembered: dict | None = None
) -> dict | None:
    """Распознать явную сверку NASA и уточнения к ней без смешения с делом катушки."""
    archive = r"\bnasa\b|\bнаса\b|(?:аполлон|apollo)[ -]*11"
    position = r"(?:^|\s)(?:с|от|на отметке|с отметки)\s*(-?\d+(?:[,.]\d+)?)\s*(?:секунд\w*|с\b)"
    timestamp = r"(?<!\d)(\d{1,2}):([0-5]\d(?:[.,]\d+)?)(?!\d)"
    another = r"перв\w* шаг|друг\w* (?:реплик|передач)|контрольн\w* (?:запис|реплик)"
    calibration = r"учебн\w* копи|калибровочн\w* (?:запис|копи)"
    named = re.search(archive, question, re.IGNORECASE)
    continued = (
        remembered is not None or re.search(archive, previous, re.IGNORECASE)
    ) and re.match(
        r"\s*(?:а\b|теперь\b|с\s+[-\d]|сравни\b|сверь\b|проверь\b|учти\b|повтори\b|без учета)",
        question,
        re.IGNORECASE,
    )
    if not (
        named
        and re.search(
            r"свер|сравн|спектр|образец|похож|скорост", question, re.IGNORECASE
        )
        or continued
    ):
        return None
    if not named and re.search(r"катушк|эфирн\w* час|позывн", question, re.IGNORECASE):
        return None
    previous_data = remembered or {}
    at = previous_data.get("at") if continued else None
    for text in (question, previous if continued else ""):
        clock = re.search(timestamp, text)
        number = re.search(position, text, re.IGNORECASE)
        if clock:
            at = int(clock[1]) * 60 + float(clock[2].replace(",", "."))
            break
        if number:
            at = float(number[1].replace(",", "."))
            break
    target = (
        previous_data.get("candidate", "eagle-extended")
        if continued
        else "eagle-extended"
    )
    target_text = question
    if (
        continued
        and not previous_data
        and not re.search(
            another + "|" + calibration + r"|расширен|длинн", question, re.IGNORECASE
        )
    ):
        target_text = previous
    for pattern, candidate in (
        (calibration, "calibration"),
        (another, "small-step"),
        (r"расширен|длинн", "eagle-extended"),
    ):
        if re.search(pattern, target_text, re.IGNORECASE):
            target = candidate
            break
    scan = bool(continued and previous_data.get("scan_speed"))
    if re.search(r"скорост", question, re.IGNORECASE):
        scan = not re.search(
            r"без (?:учета |учёта |перебора |поправки )?скорост|не (?:меняй|учитывай) скорост",
            question,
            re.IGNORECASE,
        )
    return {"at": at, "candidate": target, **({"scan_speed": True} if scan else {})}


def measurement_for(question: str) -> str:
    if re.search(
        r"по звуку|по фонограмм\w* повтор|похож\w* (?:звук|фрагмент)|звучит так же",
        question,
        re.IGNORECASE,
    ):
        return "match_sound"
    if re.search(r"\b\d{1,2}:\d{2}\b", question) and re.search(
        r"эфир", question, re.IGNORECASE
    ):
        return "locate_marker"
    if re.search(
        r"через сколько.*после|сколько.*прош\w* (?:на ленте )?(?:от|между)|интервал (?:на (?:ленте|копии) )?от|сколько.*на (?:ленте|копии).*между",
        question,
        re.IGNORECASE,
    ):
        return "tape_span"
    if re.search(r"(?:на\s*)?сколько", question, re.IGNORECASE) and re.search(
        r"опозд|позже|раньше|разош|отклон|задерж", question, re.IGNORECASE
    ):
        return "locate_marker"
    if re.search(
        r"между .*удар|(?:не хватает|пропало|потеряно).*секунд|сколько секунд|сравни.*интервал|длительност",
        question,
        re.IGNORECASE,
    ):
        return "compare_span"
    if re.search(
        r"во сколько|эфирно[емг]+ времен|эфирное время|когда прозвучал|насколько .*план|время .*эфир",
        question,
        re.IGNORECASE,
    ):
        return "locate_marker"
    return ""


def explanation_in(question: str, measurement: str) -> str:
    """Отделить часть составного вопроса, для которой нужна дополнительная цитата."""
    if measurement not in {"locate_marker", "compare_span"}:
        return ""
    clause = re.search(
        r"(?:почему|отчего|доказан\w* ли|подтвержд\w* ли|(?:в чем|какова) причина|что (?:именно )?(?:исчезло|пропало))\b.*",
        question,
        re.IGNORECASE,
    )
    return clause.group() if clause else ""


def marker_scores(case: dict, question: str) -> dict[str, int]:
    words = set(terms(question))
    return {
        m["id"]: len(words.intersection(terms(m["label"]))) for m in case["markers"]
    }


def named_marker(case: dict, question: str) -> str | None:
    """Если в вопросе названа конкретная метка, итог должен относиться к ней."""
    scores = marker_scores(case, question)
    best = max(scores.values(), default=0)
    matches = [key for key, score in scores.items() if score == best and score > 0]
    return matches[0] if len(matches) == 1 else None


def missing_person_role(case, question):
    # Наличие в программе слова «концерт» еще не подтверждает, кто дирижировал.
    relation = re.search(
        r"\bкто\s+(?:(?:был[аи]?|это)\s+)?([а-яё]{4,})", question, re.IGNORECASE
    )
    if not relation:
        return False
    wanted = set(terms(relation.group(1)))
    texts = (d["title"] + " " + d["text"] for d in case["documents"])
    return bool(wanted) and all(wanted.isdisjoint(terms(text)) for text in texts)
