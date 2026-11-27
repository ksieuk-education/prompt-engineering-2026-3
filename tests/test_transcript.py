import asyncio
import json

import httpx

from studio import transcript as archive
from studio import transcript_agent
from studio.transcript_agent import choose_source, line_information
from studio.transcript_questions import (
    cross_clock,
    literal_query,
    matches_identifiers,
    named_speaker,
    opens_page,
    requested,
    requested_field,
)


def test_optional_translation_respects_positive_and_contradictory_evidence(monkeypatch):
    monkeypatch.setenv("ARCHIVE_ARGOS_DIR", "model")
    monkeypatch.delenv("ARCHIVE_ARGOS_MODE", raising=False)
    calls = []

    async def translate(*args):
        return ["first wording"]

    monkeypatch.setattr(transcript_agent, "translate", translate)
    monkeypatch.setattr(
        transcript_agent.argos_translation, "queries", lambda *args: ["second wording"]
    )
    for primary_match, counter, expected in [
        (True, False, 1),
        (False, True, 1),
        (False, False, 2),
    ]:
        calls.clear()

        async def check(
            question, queries, tool, *args, positive=primary_match, contradicts=counter
        ):
            calls.append(tool)
            matched = positive or tool == "argos_terms"
            review = [{"id": 7, "quantity_difference": {}}] if contradicts else []
            return transcript_agent.PassageSearch(
                [{"id": 5}] if matched else [], queries[0], "fts", "", review
            )

        monkeypatch.setattr(transcript_agent, "check_translation", check)
        result = asyncio.run(
            transcript_agent.search_description("вопрос", None, "", "", None, [])
        )
        assert len(calls) == expected
        assert bool(result.matches) == (primary_match or not counter)


def test_can_reopen_the_printed_page_and_its_neighbours():
    found = archive.search_transcript("the Eagle has landed")
    assert found["edition_pages"] == 624 and found["edition_lines"] == 8452
    (row,) = found["matches"]
    assert (row["page"], row["get"], row["speaker"]) == (
        317,
        "102:46:04",
        "CDR (TRANQ)",
    )
    assert row["text"] in " ".join(archive.source_page(317)["paragraphs"])
    assert "turn blue" in archive.adjacent(row["id"], 1)["text"]
    assert "Tranquility Base" in archive.adjacent(row["id"], -1)["text"]
    assert archive.row_link(row).startswith(archive.SOURCE + "#:~:text=")


def test_page_address_restricts_a_quote_instead_of_only_opening_the_folio():
    assert opens_page("Открой страницу 491 стенограммы NASA.")
    assert not opens_page(
        "Найди в стенограмме NASA на странице 578 фразу «three cups of coffee»."
    )
    assert (
        archive.search_transcript("three cups of coffee", page=87, exact=True)[
            "matches"
        ][0]["id"]
        == 1212
    )
    assert not archive.search_transcript("three cups of coffee", page=578, exact=True)[
        "matches"
    ]
    assert (
        archive.search_transcript("two cups of coffee", page=578, exact=True)[
            "matches"
        ][0]["id"]
        == 7869
    )


def test_global_search_and_ends_of_edition():
    first = archive.search_transcript("Roger clock")["matches"][0]
    last = archive.search_transcript("splashdown")["matches"][0]
    assert first["page"] == 1 and archive.adjacent(first["id"], -1) is None
    assert last["page"] == 624 and archive.adjacent(last["id"], 1) is None
    assert archive.source_page(0) is None and archive.source_page(625) is None
    assert archive.search_transcript("purple pineapple orchestra")["mode"] == "no_match"
    assert archive.search_transcript("the a and")["mode"] == "no_terms"
    assert archive.search_transcript("charcoal powdered")["matches"][0]["page"] == 377


def test_corrected_page_keeps_old_line_ids_and_follows_the_printed_order():
    info = archive.page_info(491)
    assert info["lines"] == 17
    assert archive.source_page(491)["local_scan"].endswith(".pdf")
    rows = [r for r in archive.catalogue() if r["page"] == 491]
    assert rows[0]["id"] == 8436 and (rows[0]["get"], rows[-1]["get"]) == (
        "130:04:54",
        "130:10:12",
    )
    assert archive.adjacent(rows[0]["id"], -1)["page"] == 490
    assert archive.adjacent(rows[-1]["id"], 1)["page"] == 492
    assert archive.adjacent(8435, 1) is None
    assert archive.search_transcript("not satisfactory")["matches"][0]["page"] == 491
    assert archive.row_link(rows[0]) == archive.supplement()["source"]
    assert archive.page_info(625)["status"] == "missing"
    assert any(
        r["get"] is None and r["printed_clock"] == "05 60 33 19"
        for r in archive.catalogue()
    )


def test_field_sources_and_dialogue_context_are_independent():
    assert requested("Где в стенограмме NASA сказали о посадке?", {})
    assert not requested("Какое расстояние от Земли до Луны?", {})
    assert not requested("А на катушке какой позывной?", {"реплика_nasa": 4370})
    assert requested("А что сказали затем?", {"реплика_nasa": 4370})
    assert literal_query("Найди в стенограмме NASA «turn blue».") == "turn blue"
    assert literal_query("Что в стенограмме Apollo 11 про шаг?") == ""
    assert cross_clock(
        "Какое время от старта миссии соответствует отметке 00:03,41 в этом WAV?",
        {"открытая_сверка": {"at": 2.5}},
    )
    assert cross_clock(
        "Если в стенограмме 102:46:04, какую секунду короткого WAV нужно открыть?",
        {"реплика_nasa": 4370},
    )
    assert not cross_clock("Где в стенограмме NASA сказали о посадке?", {})


def test_only_a_quote_present_in_the_returned_line_can_support_an_answer():
    rows = [
        {"id": 11, "speaker": "CC", "role": "", "text": "We are ready here."},
        {"id": 12, "speaker": "CDR", "role": "", "text": "Magnificent desolation."},
    ]

    async def choose(quote, selected):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "message": {
                        "content": json.dumps({"quote": quote, "selected": selected})
                    }
                },
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await choose_source(
                "Как описали пейзаж?", rows, client, "http://model", "test"
            )

    assert asyncio.run(choose("Magnificent desolation", 1))[0]["id"] == 12
    assert asyncio.run(choose("Something else entirely", 1))[0] is None
    assert asyncio.run(choose("We are ready here", 0))[0] is None


def test_author_filter_precedes_limit_and_verbatim_quotes_use_the_printed_words():
    assert archive.search_transcript("Roger", limit=1)["matches"][0]["speaker"] == "CDR"
    assert (
        archive.search_transcript("Roger", limit=1, speaker="LMP")["matches"][0][
            "speaker"
        ]
        == "LMP"
    )
    assert (
        archive.search_transcript("the Eagle has landed", speaker="CMP", exact=True)[
            "matches"
        ]
        == []
    )
    assert (
        archive.search_transcript("the Eagle has landed", exact=True)["matches"][0][
            "page"
        ]
        == 317
    )
    assert not archive.search_transcript("charcoal powdered", exact=True)["matches"]
    assert named_speaker("Покажи слова Олдрина про запустение.") == "LMP"
    assert named_speaker("Найди слова Коллинза об Армстронге.") == "CMP"
    assert not named_speaker("Найди упоминание об Олдрине.")


def test_followup_reads_actual_metadata_without_guessing_a_personal_name():
    async def instrument(tool, arguments):
        assert tool == "read_transcript"
        return {"line": archive.adjacent(arguments["line_id"], 0)}

    line = archive.search_transcript("turn blue", exact=True)["matches"][0]
    previous = {"реплика_nasa": line["id"]}
    for question, field, expected in (
        ("Кто это сказал?", "speaker", "Личное имя"),
        ("А когда?", "time", "102:46:06"),
        ("На какой странице?", "page", "317"),
    ):
        assert requested(question, previous)
        assert requested_field(question) == field
        result = asyncio.run(line_information(field, previous, instrument))["result"]
        assert expected in result["answer"] and result["sources"] == ["AP11-317"]
    empty = asyncio.run(line_information("speaker", {"реплика_nasa": 0}, instrument))
    assert empty["result"]["status"] == "needs_input" and not empty["steps"]


def test_identifiers_survive_informal_translation_and_spelling():
    assert not matches_identifiers("Они использовали Wi-Fi?", "We have VHF contact.")
    assert matches_identifiers("Связь по Wi-Fi?", "The WiFi network.")
    assert matches_identifiers(
        "В стенограмме Apollo‑11 найдите S-band", "Using the S band now"
    )


def test_mixed_language_action_keeps_the_identifier_and_reaches_the_source_verifier():
    assert (
        literal_query("На странице 397 стенограммы NASA достали ли камеру из MESA?")
        == ""
    )
    assert (
        literal_query("Найди в стенограмме NASA слово MESA на странице 397.") == "MESA"
    )
    assert literal_query("Найди в стенограмме NASA «MESA».") == "MESA"
    assert matches_identifiers(
        "Положили ли камеру в MESA по стенограмме NASA?",
        "We removed the camera from the MESA.",
    )
    assert not matches_identifiers(
        "Положили ли камеру в MESA?", "We removed the camera from the hatch."
    )
    assert matches_identifiers(
        "Что командир CDR сообщил NASA?", "Houston, how do you read?"
    )


def test_a_rejected_candidate_can_only_be_replaced_with_a_checked_source(monkeypatch):
    color = archive.search_transcript("bluish-green", exact=True)["matches"][0]
    laser = archive.search_transcript("blue-green laser", exact=True)["matches"][0]
    rows = [color, laser]
    hints = {"anchors": [{"id": laser["id"], "quote": "blue-green laser"}]}

    async def translate(*args):
        return ["blue-green laser"]

    async def choose(*args):
        return color, color["text"]

    async def instrument(tool, arguments):
        if tool == "search_transcript":
            return {"matches": [], "mode": "no_match"}
        assert tool == "rank_transcript"
        return {"mode": "fts", "candidates": rows, "hints": hints}

    monkeypatch.setattr(transcript_agent, "translate", translate)
    monkeypatch.setattr(transcript_agent, "choose_source", choose)
    for trusted in (laser["id"], None):

        async def supports(question, row, quote, *args, accepted=trusted):
            return row["id"] == accepted

        monkeypatch.setattr(transcript_agent, "supports_question", supports)
        found = asyncio.run(
            transcript_agent.answer(
                "Где в стенограмме NASA говорили о лазере?",
                {},
                None,
                "",
                "",
                instrument,
            )
        )
        result = found["result"]
        assert sum(step["tool"] == "verify_transcript" for step in found["steps"]) == 2
        if trusted:
            assert (
                result["sources"] == ["AP11-123"]
                and result["transcript"]["matches"][0]["id"] == trusted
            )
        else:
            assert (
                result["status"] == "no_evidence"
                and not result["sources"]
                and not result["transcript"]["matches"]
            )
            assert [r["id"] for r in result["transcript"]["review_candidates"]] == [
                laser["id"]
            ]
