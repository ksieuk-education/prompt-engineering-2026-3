"""Заключение состоит из измерения или предложений, выбранных из открытых документов."""

import re
from collections import Counter

from .archive import terms


def passages(steps: list) -> dict[str, str]:
    result = {}
    for step in steps:
        for doc in step["output"].get("documents", []):
            sentences = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])", doc["text"])
            result.update({f"{doc['id']}.{i}": s for i, s in enumerate(sentences, 1)})
    return result


def explicit_limitations(question: str, available: dict[str, str]) -> list[str]:
    """Найти источник, который прямо оговаривает отсутствие нужного подтверждения."""
    generic = set(
        terms(
            "дело архив запись эфир время документ звук материал метка копия секунда доказательство"
        )
    )
    wanted = {term for term in terms(question) if len(term) > 3} - generic
    if not wanted:
        return []
    words = {key: set(terms(sentence)) for key, sentence in available.items()}
    frequency = Counter(term for row in words.values() for term in row)
    scores = {}
    for key, sentence in available.items():
        if not re.search(
            r"\bнет\b|не зафиксирован|не устанавлива|не поступил|неизвест|остается предполож|отсутств|не заполн",
            sentence,
            re.IGNORECASE,
        ):
            continue
        common = words[key] & wanted
        if common:
            scores[key] = sum(1 / frequency[term] for term in common)
    if not scores:
        return []
    best = max(scores.values())
    best_keys = [key for key, score in scores.items() if score == best]
    return best_keys[:2] if len({key.split(".")[0] for key in best_keys}) == 1 else []


def describe(m: dict) -> str:
    if m.get("kind") in {"tape_position", "tape_span", "public_audio"}:
        return m["detail"]
    if m.get("kind") == "audio":
        return (
            m["detail"] if m["status"] == "matched" else m["value"] + ". " + m["detail"]
        )
    if "marker" in m:
        prefix = f"Метка «{m['label']}» стоит на {m['tape']} от начала копии."
        if m["status"] == "insufficient":
            plan = (
                f" По сетке планировалось {m['planned']}." if m.get("planned") else ""
            )
            reason = m["detail"].removeprefix(f"На ленте {m['tape']}. ")
            return f"{prefix}{plan} Эфирное время установить нельзя. {reason}"
        answer = f"Метка «{m['label']}» прозвучала в {m['value']} по эфирным часам."
        if "shift_seconds" in m:
            difference = m["shift_seconds"]
            if difference == 0:
                return answer + " Время совпало с сеткой."
            direction = "позже" if difference > 0 else "раньше"
            return (
                answer
                + f" Это на {abs(difference)} с {direction} планового времени {m['planned']}."
            )
        return answer + f" На ленте это {m['tape']}."
    if m["status"] == "insufficient":
        return m["detail"]
    delta = m["missing_seconds"]
    if delta > 0:
        difference = f"Копия короче на {delta} с."
    elif delta < 0:
        difference = f"Копия длиннее на {-delta} с."
    else:
        difference = "Длительности совпадают."
    return f"Между опорами в эфире прошло {m['air_seconds']} с, на копии — {m['tape_seconds']} с. {difference}"
