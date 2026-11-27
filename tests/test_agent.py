import asyncio

import httpx

from studio import agent
from studio.archive import CASES
from studio.conclusion import explicit_limitations, passages
from studio.questions import public_request
from studio.tape_position import request as position_request


def test_short_marker_followups_preserve_the_scale_and_resolve_ties():
    case = CASES["splice"]
    prompt = "На какой секунде на копии удар?"
    assert position_request(prompt, case, {}) == {
        "basis": "tape",
        "choices": ["first", "last"],
    }
    last = {"метка_копии": {"marker": "", "basis": "tape"}}
    assert position_request("Второй.", case, last)["choices"] == ["last"]
    last["метка_копии"]["marker"] = "last"
    assert position_request(
        "А в эфире во сколько прозвучал этот же удар?", case, last
    ) == {"basis": "air", "choices": ["last"]}
    assert position_request("А почему был второй удар?", case, last) is None
    assert position_request("На какой секунде матча забили гол?", case, {}) is None
    assert (
        position_request("На какой секунде копии слышен телефон?", case, last)[
            "choices"
        ]
        == []
    )


def test_public_archive_clarification_preserves_scope_and_counter():
    assert public_request("Во сколько началась посадка на Марс?") is None
    assert public_request("Сверь записи NASA по спектру.") == {
        "at": None,
        "candidate": "eagle-extended",
    }
    last = "Сравни записи NASA с 2,50 с с расширенной версией"
    assert public_request("А теперь сравни с другой репликой.", last) == {
        "at": 2.5,
        "candidate": "small-step",
    }
    assert public_request("Сравни NASA с отметки 00:03,20.")["at"] == 3.2


def test_speed_and_candidate_can_be_changed_independently_in_dialogue():
    asked = public_request(
        "Сравни образец NASA с 2,50 с с учебной копией с учетом скорости."
    )
    assert asked == {"candidate": "calibration", "at": 2.5, "scan_speed": True}
    assert public_request("А теперь с другой репликой.", remembered=asked) == {
        **asked,
        "candidate": "small-step",
    }
    assert public_request("Повтори без учета скорости.", remembered=asked) == {
        "candidate": "calibration",
        "at": 2.5,
    }
    assert public_request("А на катушке где позывной?", remembered=asked) is None


def test_named_marker_survives_subsequent_observations():
    case = CASES["untimed"]
    assert (
        agent.named_marker(case, "Можно ли установить точное эфирное время заставки?")
        == "ident"
    )
    assert agent.named_marker(case, "Во сколько был щелчок пуска?") == "noise"
    assert agent.named_marker(case, "Который был час?") is None


def test_seconds_can_refer_to_a_clock_delay_or_a_missing_span():
    assert (
        agent.measurement_for("На сколько секунд позывной опоздал?") == "locate_marker"
    )
    assert (
        agent.measurement_for("Сколько секунд не хватает между ударами?")
        == "compare_span"
    )
    assert not agent.measurement_for("Почему позывной опоздал?")
    assert (
        agent.measurement_for(
            "Через сколько секунд после контрольного тона начинается позывной?"
        )
        == "tape_span"
    )


def test_person_question_needs_evidence_of_the_role():
    assert agent.missing_person_role(CASES["splice"], "Кто дирижировал концертом?")
    assert not agent.missing_person_role(
        CASES["signal"], "Кто подписал помету о смене пластинки?"
    )


def test_explicit_document_caveat_must_name_the_subject():
    available = passages([{"output": {"documents": CASES["splice"]["documents"]}}])
    assert explicit_limitations("Были ли аплодисменты?", available) == ["B4.2"]
    assert not explicit_limitations("Есть ли запись о стоимости билета?", available)


def test_unobserved_citation_gets_another_turn(monkeypatch):
    attempts = []

    async def model(client, context, final_only=False):
        attempts.append(context["уточнение"])
        fact = "C1.1" if len(attempts) == 1 else "A4.2"
        return agent.Decision(action="answer", argument="", marker_id="", facts=[fact])

    monkeypatch.setattr(agent, "model_step", model)

    async def run():
        async with httpx.AsyncClient() as http:
            return await agent.build_graph(http, None).ainvoke(
                {
                    "case": "signal",
                    "question": "Кто подписал помету о смене пластинки?",
                    "history": [],
                }
            )

    state = asyncio.run(run())
    assert state["result"]["sources"] == ["A4"] and len(attempts) == 2
    assert "наблюдений" in attempts[1] and "нет подписи" in state["result"]["answer"]
