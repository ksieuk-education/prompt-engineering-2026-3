"""Живое сравнение версий архивиста. Ключи проверки приложению не передаются."""

import argparse
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CONTROL = json.loads((ROOT / "tools/control.json").read_text())
READING_SUITES = {
    suite: {
        row["key"]: row for row in json.loads((ROOT / "tools" / filename).read_text())
    }
    for suite, filename in {
        "independent": "independent_transcript.json",
        "press": "press_transcript.json",
        "cabin": "cabin_transcript.json",
        "cargo": "cargo_transcript.json",
        "stowage": "stowage_transcript.json",
    }.items()
}
ORIGINAL = [
    (f"original/{case['id']}/{i}", case["id"], case["id"], question)
    for case in json.loads((ROOT / "data/cases.json").read_text())
    for i, question in enumerate(case["questions"])
]

# Один ключ диалога означает одну последовательность вопросов в собственной сессии.
CASES = [
    (
        "compound",
        "compound",
        "signal",
        "Во сколько прозвучал позывной и доказано ли, что задержка была из-за смены пластинки?",
    ),
    ("wall", "chimes", "splice", "Во сколько по эфирным часам был второй удар?"),
    ("followup", "chimes", "splice", "А первый?"),
    (
        "plan",
        "schedule",
        "untimed",
        "Верно ли, что заставка вышла в эфир ровно в 09:40:00?",
    ),
    (
        "tape",
        "local",
        "signal",
        "На какой секунде копии начинается музыкальная отбивка?",
    ),
    ("outside", "outside", "signal", "Какое расстояние от Земли до Луны?"),
]
AUDIO = [
    (
        "motif",
        "motif",
        "signal",
        "Найди по звуку, где еще в архиве встречаются эти три ноты позывного.",
    ),
    (
        "bell",
        "bell",
        "splice",
        "Найди по фонограмме повтор первого удара на этой катушке.",
    ),
    ("unique", "unique", "signal", "Поищи по звуку повтор контрольного тона в архиве."),
]
TRANSFER = [
    ("foreign_clock", "mars", "signal", "Во сколько состоялась посадка на Марс?"),
    (
        "tape_interval",
        "interval",
        "signal",
        "Через сколько секунд после контрольного тона начинается позывной?",
    ),
    (
        "uncertain_middle",
        "room",
        "splice",
        "Можно ли поставить шум зала ровно на 19:05:19 эфирного времени?",
    ),
    (
        "applause",
        "claps",
        "splice",
        "Есть ли доказательство, что в пропуске были аплодисменты?",
    ),
    (
        "signature",
        "signature",
        "signal",
        "Дежурный подписал конверт со сменой пластинки?",
    ),
    ("conductor", "conductor", "splice", "Кто дирижировал концертом?"),
]


FIELD = [
    ("field-start", "nasa", "signal", "Сверь две записи NASA по спектру."),
    ("field-positive", "nasa", "signal", "с 2,50 с"),
    (
        "field-negative",
        "nasa",
        "signal",
        "А теперь сравни с другой репликой о первом шаге.",
    ),
    (
        "field-edge",
        "edge",
        "signal",
        "Сравни образец NASA с 8 с с расширенной версией.",
    ),
]

REPEATS = [
    (
        "motif",
        "outbound",
        "signal",
        "Найди по звуку, где еще в архиве встречаются эти три ноты позывного.",
    ),
    (
        "reel/unknown",
        "outbound",
        "signal",
        "Можно ли установить эфирное время у найденного повтора на другой катушке?",
    ),
    (
        "reel/identity",
        "outbound",
        "signal",
        "Значит ли звуковое совпадение, что это был один и тот же эфир?",
    ),
    (
        "reel/return-search",
        "inbound",
        "untimed",
        "Найди по звуку повтор начала заставки в архиве.",
    ),
    (
        "reel/known",
        "inbound",
        "untimed",
        "А какое эфирное время у найденного повтора на другой катушке?",
    ),
    (
        "bell",
        "paired",
        "splice",
        "Найди по фонограмме повтор первого удара на этой катушке.",
    ),
    (
        "reel/bell-clock",
        "paired",
        "splice",
        "Сравни эфирное время исходного удара и найденного повтора.",
    ),
    ("unique", "none", "signal", "Поищи по звуку повтор контрольного тона в архиве."),
    ("reel/none", "none", "signal", "А во сколько был эфир у найденного повтора?"),
]

SCOPED = [
    (
        "scoped/coffee-made",
        "scope-a",
        "signal",
        "Найди в стенограмме NASA на странице 87 фразу «three cups of coffee».",
    ),
    (
        "scoped/coffee-drunk",
        "scope-b",
        "signal",
        "Найди в стенограмме NASA на странице 578 фразу «two cups of coffee».",
    ),
    (
        "scoped/wrong-page",
        "scope-c",
        "signal",
        "Найди в стенограмме NASA на странице 578 фразу «three cups of coffee».",
    ),
    (
        "scoped/quantity",
        "scope-counter",
        "signal",
        "Где в стенограмме NASA на странице 578 сказано, что за завтраком с персиками выпили три чашки кофе?",
    ),
    (
        "scoped/boxes",
        "scope-boxes",
        "signal",
        "Найди в стенограмме NASA на странице 544 фразу о двух ящиках с лунными образцами, запечатанных в вакууме.",
    ),
    (
        "scoped/missing",
        "scope-missing",
        "signal",
        "Найди на странице 625 стенограммы NASA фразу «splashdown».",
    ),
]

SPEED = [
    (
        "speed/calibration",
        "speed-memory",
        "signal",
        "Сравни образец NASA с 2,50 с с учебной копией с учетом скорости.",
    ),
    ("speed/no-scan", "speed-memory", "signal", "Повтори без учета скорости."),
    ("speed/again", "speed-memory", "signal", "А теперь учти изменение скорости."),
    (
        "speed/control",
        "speed-memory",
        "signal",
        "А теперь сравни с другой репликой о первом шаге.",
    ),
    (
        "speed/published",
        "original-editions",
        "signal",
        "Сверь образец NASA с 2,50 с с расширенной версией с учетом скорости.",
    ),
]

TRANSCRIPT = [
    ("document-start", "folio", "signal", "Открой стенограмму NASA."),
    ("document-landing", "folio", "signal", "The Eagle has landed"),
    ("document-next", "folio", "signal", "Что ответили затем?"),
    ("document-back", "folio", "signal", "А перед этой репликой?"),
    (
        "document-step",
        "step",
        "untimed",
        "Найди в стенограмме Apollo 11 слова про один маленький шаг для человека.",
    ),
    (
        "document-absent",
        "blank",
        "splice",
        "Найди в стенограмме NASA «purple pineapple orchestra».",
    ),
    ("document-last", "end", "signal", "Найди в стенограмме NASA «splashdown»."),
    ("document-edge", "end", "signal", "Какая следующая реплика?"),
]

# Страницы сверены по изданию до первого прогона русских пересказов.
PARAPHRASES = {
    "dust": (
        "С чем в стенограмме NASA астронавт сравнил пыль, прилипшую к подошвам ботинок?",
        377,
        "powdered charcoal",
    ),
    "crater": (
        "Найди в стенограмме Apollo 11 рассказ о кратере размером с футбольное поле.",
        319,
        "football field",
    ),
    "desolation": (
        "Найди в стенограмме NASA слова Олдрина про величественное запустение.",
        382,
        "magnificent desolation",
    ),
    "breath": (
        "В каком месте стенограммы NASA Хьюстон после посадки сказал, что они снова дышат?",
        317,
        "breathing again",
    ),
    "curiosity": (
        "Где в стенограмме Apollo 11 говорится о неутолимом любопытстве человечества?",
        589,
        "insatiable curiosity",
    ),
    "cheese": (
        "В каком месте стенограммы NASA говорится, что Луна сделана из зеленого сыра?",
        None,
        "",
    ),
    "trio": (
        "Найди в стенограмме Apollo 11 слова про фиолетовый ананасовый оркестр.",
        None,
        "",
    ),
}


NEW_PARAPHRASES = {
    "earthling": (
        "Где в стенограмме NASA встречают собеседника приветствием «привет, землянин»?",
        170,
        "hello there, earthling",
    ),
    "lounge": (
        "Найди в стенограмме Apollo 11 сравнение качества слышимости с беседой в собственной гостиной.",
        2,
        "sitting in your living room",
    ),
    "laser": (
        "Где в стенограмме NASA с Земли предлагают мигать сине-зеленым лазером?",
        123,
        "blue-green laser",
    ),
    "hippo": ("Найди в стенограмме NASA стихотворение о зеленом бегемоте.", None, ""),
    "wifi": (
        "Где в стенограмме Apollo 11 описано подключение космонавтов к сети Wi-Fi на Луне?",
        None,
        "",
    ),
}

# Отдельные проверочные вопросы. Эталон прочитан в стенограмме до запусков этой серии.
HOLDOUT = {
    "oatmeal": (
        "Где в стенограмме NASA предлагают записать Олдрина на соревнование по поеданию овсянки?",
        147,
        "aldrin in the oatmeal eating contest",
    ),
    "breakfast": (
        "В каком месте стенограммы NASA перечисляют завтрак с нарезанными персиками, колбасными котлетами и двумя чашками кофе?",
        578,
        "two cups of coffee",
    ),
    "california": (
        "Найди в стенограмме Apollo 11, как Армстронг поздравляет Калифорнию с двухсотлетием.",
        30,
        "birthday of california",
    ),
    "winner": (
        "Найди в стенограмме NASA сообщение, что Олдрин победил в соревновании по поеданию овсянки.",
        None,
        "",
    ),
    "three-cups": (
        "Где в стенограмме NASA говорит, что за завтраком с персиками астронавт выпил три чашки кофе?",
        None,
        "",
    ),
    "moon-maple": (
        "Найди в стенограмме Apollo 11 фразу о добыче кленового сиропа на поверхности Луны.",
        None,
        "",
    ),
}

EDITION = [
    ("folio-open", "pages", "signal", "Открой страницу 491 стенограммы NASA."),
    ("folio-missing", "pages", "signal", "Открой страницу 625 стенограммы NASA."),
    (
        "folio-citation",
        "corrected",
        "signal",
        "Найди в стенограмме NASA «if that's not satisfactory».",
    ),
    (
        "field-positive",
        "audio-clocks",
        "signal",
        "Сравни образец NASA с 2,50 с с расширенной версией.",
    ),
    (
        "folio-from-audio",
        "audio-clocks",
        "signal",
        "Какое время от старта миссии соответствует отметке 00:03,41 в этом WAV?",
    ),
    (
        "document-landing",
        "doc-clocks",
        "signal",
        "Найди в стенограмме NASA «the Eagle has landed».",
    ),
    (
        "folio-from-text",
        "doc-clocks",
        "signal",
        "Если в стенограмме 102:46:04, какую секунду короткого WAV нужно открыть?",
    ),
]


# Короткие вопросы с общим conversation обращаются к уже найденной строке.
WITNESSES = {
    "right-speaker": (
        "landing",
        "Найди в стенограмме NASA слова Армстронга «the Eagle has landed».",
        "CDR",
        317,
    ),
    "who": ("landing", "Кто это сказал?", "CDR", 317),
    "time": ("landing", "А какое время миссии у этой фразы?", "CDR", 317),
    "wrong-speaker": (
        "collins",
        "Найди в стенограмме NASA реплику Коллинза «the Eagle has landed».",
        "",
        None,
    ),
    "houston": (
        "ground",
        "Найди в стенограмме NASA слова Хьюстона «turn blue».",
        "CC",
        317,
    ),
    "ground-who": ("ground", "Кто именно это сказал?", "CC", 317),
    "wrong-connection": (
        "connection",
        "Найди в стенограмме Apollo 11 место, где говорится об отправке данных через USB-C.",
        "",
        None,
    ),
    "window": (
        "window",
        "Найди в стенограмме NASA слова о том, что космонавту наконец дали окно, чтобы смотреть наружу.",
        "CDR",
        2,
    ),
}


def matches_paraphrase(name, row):
    _, page, phrase = (PARAPHRASES | NEW_PARAPHRASES | HOLDOUT)[name]
    # Кратер обсуждают трижды: во время посадки и в двух последующих разговорах.
    valid_pages = {319, 429, 450} if name == "crater" else {page}
    return row["page"] in valid_pages and phrase in row["text"].lower()


# Эталонные номера прочитаны в печатных строках до первого прогона серии.
MISSION_POINTS = {
    "points": (
        "Что в стенограмме NASA сказано ровно на отметках 102:45:59 и 102:46:06?",
        [4369, 4371],
        "points",
        None,
    ),
    "reverse": (
        "В стенограмме NASA найди две отдельные отметки GET 102:46:06 и 102:45:59.",
        [4371, 4369],
        "points",
        None,
    ),
    "range": (
        "Покажи в стенограмме NASA все реплики между 102:45:59 и 102:46:06.",
        [4369, 4370, 4371],
        "range",
        None,
    ),
    "elapsed": (
        "Сколько секунд прошло по часам миссии NASA с 102:45:59 до 102:46:06?",
        [4369, 4371],
        "elapsed",
        7,
    ),
    "elapsed-empty": (
        "Какая разница по часам миссии NASA между 102:46:05 и 102:46:08?",
        [],
        "elapsed",
        3,
    ),
    "elapsed-reverse": (
        "Какая разница по часам миссии NASA между 102:46:06 и 102:45:59?",
        [4371, 4369],
        "elapsed",
        7,
    ),
    "same": (
        "Сколько секунд прошло по часам миссии NASA с 102:46:04 до 102:46:04?",
        [4370],
        "elapsed",
        0,
    ),
    "mixed": (
        "Что сказано в стенограмме NASA в 102:46:04 и в 102:46:05?",
        [4370],
        "points",
        None,
    ),
    "both-editions": (
        "Покажи две отметки стенограммы NASA на странице 234: 078:46:31 и 126:46:31.",
        [3145],
        "points",
        None,
    ),
}

MISSION_TIMES = {
    "landing": (
        "landing",
        "Что в стенограмме NASA сказано в 102:46:04 от старта миссии?",
        "answered",
        [4370],
    ),
    "landing-page": ("landing", "А на какой странице?", "answered", [4370]),
    "range": (
        "range",
        "Покажи переговоры NASA с 102:45:59 до 102:46:06 по времени миссии.",
        "answered",
        [4369, 4370, 4371],
    ),
    "which": ("range", "Кто это сказал?", "needs_input", []),
    "ground": ("range", "А в 102:46:06?", "answered", [4371]),
    "overlap": (
        "overlap",
        "Кто говорит в стенограмме NASA на отметке 007:53:01?",
        "answered",
        [653, 654],
    ),
    "collins": ("overlap", "Что в 007:53:01 сказал Коллинз?", "answered", [654]),
    "no-start": (
        "gap",
        "Есть ли начало реплики в стенограмме Apollo 11 ровно в 102:46:05?",
        "no_evidence",
        [],
    ),
    "wrong-quote": (
        "wrong",
        "Есть ли в стенограмме NASA ровно в 102:46:06 фраза «the Eagle has landed»?",
        "no_evidence",
        [],
    ),
    "separate-pages": (
        "pages",
        "На каких страницах стенограммы NASA стоит 059:26:41?",
        "answered",
        [2519, 3423],
    ),
    "one-folio": ("pages", "А на странице 253 в 059:26:41?", "answered", [3423]),
    "restored": (
        "restored",
        "Прочитай в стенограмме NASA реплику с меткой 130:04:54.",
        "answered",
        [8436],
    ),
    "invalid": (
        "invalid",
        "Покажи в стенограмме NASA 102:66:05 по времени миссии.",
        "needs_input",
        [],
    ),
    "reversed": (
        "reversed",
        "Покажи стенограмму NASA с 102:46:06 до 102:46:04.",
        "needs_input",
        [],
    ),
}


CLOCK_EDITIONS = {
    "aldrin-scan": (
        "aldrin",
        "Что в стенограмме NASA сказано в 078:46:31 на странице 234?",
        3145,
        "078:46:31",
        "126:46:31",
    ),
    "aldrin-html": (
        "aldrin-html",
        "Что в стенограмме NASA на странице 234 в 126:46:31?",
        3145,
        "078:46:31",
        "126:46:31",
    ),
    "collins-scan": (
        "collins",
        "Открой в стенограмме NASA 102:58:12 на странице 320.",
        4426,
        "102:58:12",
        "054:58:12",
    ),
    "collins-html": (
        "collins-html",
        "Прочитай в стенограмме NASA реплику на странице 320 в 054:58:12.",
        4426,
        "102:58:12",
        "054:58:12",
    ),
    "follow-time": (
        "collins-html",
        "А когда это было?",
        4426,
        "102:58:12",
        "054:58:12",
    ),
}


TAPE_POSITIONS = [
    (
        "position/music",
        "music",
        "signal",
        "На какой секунде копии начинается музыкальная отбивка?",
    ),
    ("position/tone", "music", "signal", "А контрольный тон?"),
    ("position/ident", "music", "signal", "А три ноты позывного?"),
    ("position/room", "room", "splice", "На какой отметке ленты слышен шум зала?"),
    (
        "position/click",
        "click",
        "untimed",
        "Какой таймкод у щелчка пуска на этой ленте?",
    ),
    ("position/intro", "click", "untimed", "А начало заставки?"),
    ("position/which", "strikes", "splice", "На какой секунде на копии удар?"),
    ("position/second", "strikes", "splice", "Второй."),
    (
        "position/air",
        "strikes",
        "splice",
        "А в эфире во сколько прозвучал этот же удар?",
    ),
    (
        "position/unknown",
        "unlisted",
        "signal",
        "На какой секунде копии слышен звонок телефона?",
    ),
]


def correct(key, reply):
    answer = reply["answer"].lower()
    sources = set(reply.get("sources", []))
    measurements = reply.get("measurements", [])
    suite, _, case_key = key.partition("/")
    if suite in READING_SUITES:
        expected = READING_SUITES[suite][case_key]
        matches = reply.get("transcript", {}).get("matches", [])
        if expected["id"] is None:
            if reply["status"] != "no_evidence" or matches:
                return False
            if not sources:
                return True
            row = reply.get("transcript", {}).get("counterexample", {})
            opposite = expected.get("opposite")
            movement = row.get("movement_difference", {})
            return bool(
                opposite
                and movement
                and row.get("id") == opposite["id"]
                and movement.get("requested") == opposite["requested"]
                and movement.get("observed") == opposite["observed"]
                and movement.get("source_words")
                and movement["source_words"] in row.get("text", "")
                and sources == {f"AP11-{row.get('page')}"}
            )
        return (
            reply["status"] == "answered"
            and len(matches) == 1
            and matches[0]["id"] == expected["id"]
            and expected["quote"] in matches[0]["text"].lower()
            and sources == {f"AP11-{expected['page']}"}
        )
    if key.startswith("position/"):
        name = key.split("/", 1)[1]
        if name == "which":
            return (
                reply["status"] == "needs_input"
                and "перв" in answer
                and "втор" in answer
            )
        if name == "unknown":
            return (
                reply["status"] in {"needs_input", "no_evidence"}
                and "00:" not in answer
                and "21:17:" not in answer
            )
        if name == "air":
            return (
                reply["status"] == "answered"
                and "19:05:37" in answer
                and "B1" in sources
            )
        stamp, document = {
            "music": ("00:25", "A2"),
            "tone": ("00:04", "A2"),
            "ident": ("00:18", "A2"),
            "room": ("00:12", "B2"),
            "click": ("00:03", "C2"),
            "intro": ("00:12", "C2"),
            "second": ("00:25", "B2"),
        }[name]
        return (
            reply["status"] == "answered"
            and stamp in answer
            and document in sources
            and "похожий звук" not in answer
        )
    if key.startswith("clock-edition/"):
        name = key.split("/", 1)[1]
        _, _, line_id, scan, html = CLOCK_EDITIONS[name]
        rows = reply.get("transcript", {}).get("matches", [])
        return (
            reply["status"] == "answered"
            and len(rows) == 1
            and rows[0]["id"] == line_id
            and rows[0]["get"] == scan
            and rows[0].get("html_get") == html
            and scan in answer
            and html in answer
            and "скан" in answer
            and "html" in answer
        )
    if key.startswith("clock-points/"):
        _, ids, kind, seconds = MISSION_POINTS[case_key]
        document = reply.get("transcript", {})
        clock = document.get("clock") or {}
        matches = [r["id"] for r in document.get("matches", [])]
        return (
            reply["status"] == "answered"
            and matches == ids
            and (kind == "range" or clock.get("kind") == kind)
            and (seconds is None or clock.get("seconds") == seconds)
        )
    if key.startswith("mission/"):
        name = key.split("/", 1)[1]
        _, _, status, identifiers = MISSION_TIMES[name]
        rows = reply.get("transcript", {}).get("matches", [])
        if reply["status"] != status or [r["id"] for r in rows] != identifiers:
            return False
        if name == "landing-page":
            return sources == {"AP11-317"} and "317" in answer and "страниц" in answer
        if sources != {f"AP11-{r['page']}" for r in rows}:
            return False
        tools = {step["tool"] for step in reply["steps"]}
        if name == "which":
            return "реплик" in answer and ("како" in answer or "уточн" in answer)
        if name == "no-start":
            return "размечен" in answer and "тишин" in answer
        return "search_transcript" in tools
    if key.startswith("reel/"):
        if key == "reel/return-search":
            return any(
                m.get("kind") == "audio"
                and any(
                    h["case_id"] == "signal" and abs(h["second"] - 18) < 0.04
                    for h in m.get("matches", [])
                )
                for m in measurements
            )
        if key == "reel/none":
            return (
                reply["status"] == "no_evidence"
                and not sources
                and not any("21:17:" in v for v in [answer])
            )
        if key == "reel/identity":
            return (
                any(
                    word in answer
                    for word in (
                        "не доказ",
                        "не подтвержд",
                        "не устанавлива",
                        "недостаточ",
                    )
                )
                and "эфир" in answer
                and {"A2", "C2"} <= sources
            )
        if key == "reel/bell-clock":
            return (
                {"B1", "B2"} <= sources
                and "19:05:12" in answer
                and "19:05:37" in answer
            )
        return (
            {"A2", "A3", "C2", "C3"} <= sources
            and "21:17:24" in answer
            and "00:12" in answer
            and any(
                word in answer
                for word in (
                    "нельзя",
                    "нет привязки",
                    "не установлен",
                    "не установлено",
                )
            )
            and (key != "reel/known" or "фн-014" in answer)
        )
    if key.startswith("scoped/"):
        document = reply.get("transcript", {})
        rows = document.get("matches", [])
        if key == "scoped/missing":
            return (
                reply["status"] == "no_evidence"
                and not sources
                and not rows
                and "624" in answer
            )
        if key == "scoped/wrong-page":
            return (
                reply["status"] == "no_evidence"
                and not sources
                and not rows
                and document.get("scope_page") == 578
            )
        if key == "scoped/quantity":
            counter = document.get("counterexample", {})
            return (
                reply["status"] == "no_evidence"
                and not rows
                and sources == {"AP11-578"}
                and counter.get("id") == 7869
                and counter.get("quantity_difference", {}).get("printed") == 2
            )
        expected_page, expected_id = {
            "scoped/coffee-made": (87, 1212),
            "scoped/coffee-drunk": (578, 7869),
            "scoped/boxes": (544, 7542),
        }[key]
        return (
            reply["status"] == "answered"
            and bool(rows)
            and rows[0]["id"] == expected_id
            and sources == {f"AP11-{expected_page}"}
            and document.get("scope_page") == expected_page
        )
    if key.startswith("speed/"):
        if len(measurements) != 1 or "compare_public" not in {
            s["tool"] for s in reply["steps"]
        }:
            return False
        m = measurements[0]
        if m.get("status") != "compared" or m.get("reference_second") != 2.50:
            return False
        scan = m.get("speed_scan") or {}
        if key == "speed/no-scan":
            return m.get("candidate") == "calibration" and "speed_scan" not in m
        if key in {"speed/calibration", "speed/again"}:
            return (
                m.get("candidate") == "calibration"
                and scan.get("passes")
                and abs(scan["rate_ratio"] - 1.017) <= 0.0006
                and abs(scan["second"] - (0.57 + 2.50 / 1.017)) <= 0.003
                and not m["waveform"]["passes"]
            )
        candidate = "small-step" if key == "speed/control" else "eagle-extended"
        return (
            m.get("candidate") == candidate
            and scan.get("passes") is False
            and scan.get("rate_ratio") is None
            and m["spectrum"]["passes"] == (key == "speed/published")
        )
    if key.startswith("witness/"):
        name = key.split("/", 1)[1]
        _, _, speaker, page = WITNESSES[name]
        matches = reply.get("transcript", {}).get("matches", [])
        tools = {step["tool"] for step in reply["steps"]}
        if name == "wrong-speaker":
            return (
                reply.get("transcript", {}).get("attribution")
                == {"asserted": "CMP", "actual": "CDR"}
                and bool(matches)
                and matches[0]["page"] == 317
                and sources == {"AP11-317"}
                and "коллинз" in answer
                and "армстронг" in answer
            )
        if page is None:
            return reply["status"] == "no_evidence" and not sources and not matches
        if not matches or sources != {f"AP11-{page}"}:
            return False
        row = matches[0]
        if row["speaker"].split(" ", 1)[0] != speaker or row["page"] != page:
            return False
        if name in {"who", "ground-who", "time"} and "read_transcript" not in tools:
            return False
        if name == "ground-who":
            return "имя" in answer and "хьюстон" in answer
        if name == "who":
            return "армстронг" in answer
        if name == "time":
            return row["get"] == "102:46:04" and "102:46:04" in answer
        if name == "window":
            return "window to look out" in row["text"].lower()
        return reply["status"] == "answered"
    if key.startswith("folio-"):
        doc = reply.get("transcript", {})
        events = {s["tool"] for s in reply["steps"]}
        if key == "folio-open":
            return (
                doc.get("page") == 491
                and "17" in answer
                and "AP11-491" in sources
                and "read_transcript_page" in events
            )
        if key == "folio-missing":
            return reply["status"] == "no_evidence" and not sources and "624" in answer
        if key == "folio-citation":
            hits = doc.get("matches", [])
            return (
                bool(hits)
                and hits[0]["page"] == 491
                and hits[0]["get"] == "130:04:57"
                and hits[0]["source_url"].endswith(".pdf")
            )
        return (
            doc.get("alignment") == "unavailable"
            and "clock_reference" in events
            and not measurements
            and (
                ("102:46:04" in answer and "AP11-317" in sources)
                if key == "folio-from-text"
                else not sources
            )
        )
    if key.startswith("paraphrase/"):
        name = key.split("/")[1]
        _, page, _ = (PARAPHRASES | NEW_PARAPHRASES | HOLDOUT)[name]
        rows = reply.get("transcript", {}).get("matches", [])
        calls = {s["tool"] for s in reply["steps"]}
        # Векторный поиск может принести проверяемую строку и без английских слов для FTS.
        if not calls.intersection(
            {"transcript_terms", "argos_terms"}
        ) or not calls.intersection({"search_transcript", "rank_transcript"}):
            return False
        if page is None:
            if name == "three-cups" and (
                counter := reply.get("transcript", {}).get("counterexample")
            ):
                return (
                    reply["status"] == "no_evidence"
                    and not rows
                    and sources == {"AP11-578"}
                    and counter["page"] == 578
                    and counter.get("quantity_difference")
                    == {"requested": 3, "printed": 2, "words": "two cups of coffee"}
                    and "two cups of coffee" in answer
                )
            return reply["status"] == "no_evidence" and not rows and not sources
        return bool(rows) and matches_paraphrase(name, rows[0])
    if key.startswith("document-"):
        document = reply.get("transcript", {})
        rows = document.get("matches", [])
        calls = {s["tool"] for s in reply["steps"]}
        if key == "document-start":
            return reply["status"] == "needs_input" and not rows and "фразу" in answer
        if key in {"document-absent", "document-edge"}:
            tool = (
                "search_transcript" if key == "document-absent" else "read_transcript"
            )
            return (
                reply["status"] == "no_evidence"
                and not rows
                and not sources
                and tool in calls
            )
        page, stamp, word = {
            "document-landing": (317, "102:46:04", "eagle has landed"),
            "document-next": (317, "102:46:06", "turn blue"),
            "document-back": (317, "102:46:04", "eagle has landed"),
            "document-step": (377, "109:24:48", "small step"),
            "document-last": (624, "195:18:18", "splashdown"),
        }[key]
        tool = (
            "read_transcript"
            if key in {"document-back", "document-next"}
            else "search_transcript"
        )
        return (
            bool(rows)
            and rows[0]["page"] == page
            and rows[0]["get"] == stamp
            and word in rows[0]["text"].lower()
            and sources == {f"AP11-{page}"}
            and tool in calls
            and (
                key != "document-step"
                or bool(calls & {"transcript_terms", "argos_terms"})
            )
        )
    if key == "field-start":
        return (
            reply["status"] == "needs_input"
            and not measurements
            and "секунды" in answer
        )
    if key.startswith("field-"):
        if (
            reply["status"] != "answered"
            or len(measurements) != 1
            or "compare_public" not in [s["tool"] for s in reply["steps"]]
        ):
            return False
        m = measurements[0]
        if key == "field-edge":
            return m.get("status") == "invalid_window" and "конец" in answer
        if (
            m.get("kind") != "public_audio"
            or m.get("reference_second") != 2.5
            or m.get("status") != "compared"
        ):
            return False
        if key == "field-positive":
            return (
                m["candidate"] == "eagle-extended"
                and m["spectrum"]["passes"]
                and abs(m["spectrum"]["second"] - 3.41) <= 0.03
            )
        return (
            m["candidate"] == "small-step"
            and not m["spectrum"]["passes"]
            and not m["waveform"]["passes"]
        )
    if key in {"outside", "foreign_clock", "conductor"}:
        return (
            not sources
            and not measurements
            and reply["status"] in {"answered", "no_evidence"}
            and any(
                word in answer
                for word in (
                    "не наш",
                    "нет сведений",
                    "нет данных",
                    "нет подтверждения",
                    "выходит за",
                )
            )
        )
    if reply["status"] != "answered":
        return False
    if key.startswith("original/"):
        _, case_id, turn = key.split("/")
        reference = CONTROL[case_id]
        if turn == "1":
            return bool(set(reply.get("passages", [])).intersection(reference["facts"]))
        return len(measurements) == 1 and all(
            measurements[0].get(field) == value
            for field, value in reference["measurement"].items()
        )
    if key == "tape_interval":
        return (
            "14" in answer
            and "A2" in sources
            and any(s in answer for s in ("14 с", "00:14", "14 сек"))
        )
    if key == "uncertain_middle":
        return {"B1", "B2"} <= sources and any(
            m.get("marker") == "room" and m.get("status") == "insufficient"
            for m in measurements
        )
    if key == "applause":
        return bool(sources & {"B3", "B4"}) and any(
            s in answer
            for s in (
                "не зафиксирован",
                "не устанавлива",
                "не установлен",
                "не подтверж",
            )
        )
    if key == "signature":
        return "A4" in sources and any(
            s in answer for s in ("нет подписи", "не подписан", "без подпис")
        )
    if key == "compound":
        return (
            "21:17:24" in answer
            and "A4" in sources
            and any(
                s in answer
                for s in ("предполож", "нет подписи", "не установлен", "не подтверж")
            )
        )
    if key in {"wall", "followup"}:
        expected = "19:05:37" if key == "wall" else "19:05:12"
        # В самом журнале B1 указаны оба эфирных времени. Для прямой цитаты его достаточно.
        return expected in answer and "B1" in sources
    if key == "plan":
        return (
            "09:40:00" in answer
            and {"C1", "C3"} <= sources
            and any(s in answer for s in ("нельзя", "неизвест", "отсутств"))
        )
    if key == "tape":
        return ("00:25" in answer or "25-й секунде" in answer) and "A2" in sources
    search = next((m for m in measurements if "matches" in m), None)
    if not search or "match_sound" not in [s["tool"] for s in reply["steps"]]:
        return False
    expected = {"motif": ("untimed", 12), "bell": ("splice", 25), "unique": None}[key]
    if expected is None:
        return not search["matches"] and search["status"] == "no_match"
    return any(
        m["case_id"] == expected[0] and abs(m["second"] - expected[1]) <= 0.04
        for m in search["matches"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    suites = {
        "dialogue": CASES,
        "audio": AUDIO,
        "all": CASES + AUDIO,
        "transfer": TRANSFER,
        "original": ORIGINAL,
        "field": FIELD,
        **{
            suite: [
                (f"{suite}/{key}", key, "signal", item["question"])
                for key, item in rows.items()
            ]
            for suite, rows in READING_SUITES.items()
        },
        "positions": TAPE_POSITIONS,
        "clock-editions": [
            (f"clock-edition/{key}", item[0], "signal", item[1])
            for key, item in CLOCK_EDITIONS.items()
        ],
        "clock-points": [
            (f"clock-points/{key}", key, "signal", item[0])
            for key, item in MISSION_POINTS.items()
        ],
        "mission": [
            (f"mission/{key}", item[0], "signal", item[1])
            for key, item in MISSION_TIMES.items()
        ],
        "repeats": REPEATS,
        "scoped": SCOPED,
        "speed": SPEED,
        "transcript": TRANSCRIPT,
        "edition": EDITION,
        "witnesses": [
            (f"witness/{key}", item[0], "signal", item[1])
            for key, item in WITNESSES.items()
        ],
        "paraphrase": [
            (f"paraphrase/{key}", key, "signal", row[0])
            for key, row in PARAPHRASES.items()
        ],
        "paraphrase-new": [
            (f"paraphrase/{key}", key, "signal", row[0])
            for key, row in NEW_PARAPHRASES.items()
        ],
        "holdout": [
            (f"paraphrase/{key}", key, "signal", row[0]) for key, row in HOLDOUT.items()
        ],
    }
    parser.add_argument("--suite", choices=suites, default="all")
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    questions = suites[args.suite]
    rows, sessions = [], {}
    with httpx.Client(base_url=args.url, timeout=300, trust_env=False) as client:
        health = client.get("/api/status").raise_for_status().json()
        if not health["online"]:
            raise SystemExit("Сервер не видит модель " + health["model"])
        for key, conversation, case_id, question in questions:
            if conversation not in sessions:
                sessions[conversation] = (
                    client.post("/api/sessions", json={"case_id": case_id})
                    .raise_for_status()
                    .json()["session"]
                )
            start = time.monotonic()
            try:
                result = client.post(
                    "/api/ask",
                    json={"question": question, "session": sessions[conversation]},
                )
                result.raise_for_status()
                reply = result.json()
                ok = correct(key, reply)
                row = {
                    k: reply.get(k)
                    for k in ("status", "answer", "sources", "passages", "measurements")
                }
                row["tools"] = [s["tool"] for s in reply["steps"]]
                if "transcript" in reply:
                    row["transcript"] = reply["transcript"]
            except httpx.HTTPStatusError as err:
                ok = False
                row = {
                    "status": "error",
                    "answer": str(
                        err.response.json().get("detail", err.response.status_code)
                    ),
                }
            except (httpx.HTTPError, ValueError, KeyError) as err:
                ok = False
                row = {"status": "error", "answer": str(err)}
            row.update(
                id=key,
                case=case_id,
                question=question,
                passed=ok,
                seconds=round(time.monotonic() - start, 2),
            )
            rows.append(row)
            print(
                key,
                "OK" if ok else "FAIL",
                row["seconds"],
                row["answer"][:280],
                flush=True,
            )
    report = {
        "variant": args.label,
        "model": health["model"],
        "suite": args.suite,
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
        "cases": rows,
    }
    if "action_tokens" in health:
        report["action_token_limit"] = health["action_tokens"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{report['passed']}/{report['total']} — {args.out}")


if __name__ == "__main__":
    main()
