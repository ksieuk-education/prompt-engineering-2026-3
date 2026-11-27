from studio import mission_time, transcript
from studio.transcript_questions import requested


def test_inclusive_clock_range_and_same_second_speakers():
    span = transcript.search_transcript("GET 102:45:59–102:46:06")
    assert [r["id"] for r in span["matches"]] == [4369, 4370, 4371]
    assert span["clock"] == {"start": "102:45:59", "end": "102:46:06", "total": 3}
    assert [r["id"] for r in transcript.search_transcript("7:53:01")["matches"]] == [
        653,
        654,
    ]
    assert [
        r["id"]
        for r in transcript.search_transcript("", speaker="CMP", clock="007:53:01")[
            "matches"
        ]
    ] == [654]
    assert (
        transcript.search_transcript("the Eagle has landed", clock="102:46:06")[
            "matches"
        ]
        == []
    )
    assert transcript.search_transcript("102:46:05")["clock"]["total"] == 0


def test_invalid_and_broad_intervals_do_not_substitute_unrelated_rows():
    for text in ("102:66:00", "005:00:60", "1000:00:01", "102:46:06–102:46:04"):
        result = transcript.search_transcript(text)
        assert result["mode"] == "invalid_mission_time" and not result["matches"]
    wide = transcript.search_transcript("0:00:00–999:59:59")
    assert wide["clock"]["total"] == 8449
    assert len(wide["matches"]) == mission_time.MAX_SHOWN
    assert "первые" in wide["detail"]
    assert not requested(
        "Во сколько по эфирным часам была метка 21:17:24 на катушке?", {}
    )
    assert not requested("Послушай запись NASA WAV с 00:00:02", {})


def test_printed_discontinuity_and_scanned_evidence():
    rows = transcript.search_transcript("059:26:41")["matches"]
    assert [r["page"] for r in rows] == [182, 253]
    assert "clock_neighbors" not in rows[0]
    assert rows[1]["clock_neighbors"] == ["083:26:40", "083:26:44"]
    assert transcript.search_transcript("059:26:41", page=253)["matches"] == [rows[1]]
    assert transcript.row_link(rows[1]).endswith("#page=255")
    assert transcript.source_page(253)["local_scan"].endswith("253.pdf")
    for page, line_id, scan, html, physical in (
        (234, 3145, "078:46:31", "126:46:31", 1),
        (320, 4426, "102:58:12", "054:58:12", 2),
    ):
        for query in (scan, html):
            found = transcript.search_transcript(query, page=page)
            assert len(found["matches"]) == found["clock"]["total"] == 1
            row = found["matches"][0]
            assert (row["id"], row["get"], row["html_get"]) == (line_id, scan, html)
            assert "clock_neighbors" not in row
        assert transcript.source_page(page)["local_scan"].endswith(f"#page={physical}")
        assert transcript.row_link(row).endswith(f"#page={page + 2}")


def test_every_citation_addresses_its_own_printed_lines():
    # В издании есть идентичные реплики даже на одной и той же странице.
    edition = {n: transcript.source_page(n)["paragraphs"] for n in range(1, 625)}
    for row in transcript.catalogue():
        pos = transcript.passage_position(row["page"], row["id"])
        lines = edition[row["page"]][pos["paragraph"]].splitlines()
        assert " ".join(lines[pos["start_line"] : pos["end_line"]]) == row["text"]
    assert (
        transcript.passage_position(491, 8436)["paragraph"]
        != transcript.passage_position(491, 8438)["paragraph"]
    )
    assert transcript.passage_position(490, 8438) is None
    assert transcript.passage_position(491, 0) is None


def test_listed_points_preserve_request_order_and_count_an_edition_alias_once():
    a, b = "102:45:59", "102:46:06"
    assert mission_time.find_address(f"ровно в {b} и в {a}") == f"{b}, {a}"
    assert mission_time.find_address(f"все между {a} и {b}") == f"{a}–{b}"
    points = transcript.search_transcript(f"GET {b}, GET {a}")
    assert [row["id"] for row in points["matches"]] == [4371, 4369]
    assert points["clock"]["counts"] == {b: 1, a: 1}
    aliases = transcript.search_transcript("078:46:31 или 126:46:31", page=234)
    assert aliases["clock"]["counts"] == {"078:46:31": 1, "126:46:31": 1}
    assert aliases["clock"]["total"] == 1
    assert [row["id"] for row in aliases["matches"]] == [3145]


def test_clock_arithmetic_across_hours_and_missing_or_reversed_bounds():
    def difference(question):
        data = transcript.search_transcript(mission_time.find_address(question))
        return mission_time.measure_difference(data["clock"], question)

    assert (
        difference("Сколько секунд прошло с 099:59:59 до 100:00:02?")[0]["seconds"] == 3
    )
    assert (
        difference("Какая разница между 100:00:02 и 099:59:59 по часам миссии?")[0][
            "seconds"
        ]
        == 3
    )
    assert difference("Сколько прошло с 100:00:02 до 099:59:59?")[0] is None
    assert difference("Сколько прошло с 100:00:02?")[0] is None
    assert not mission_time.asks_difference(
        "Какая разница в содержании реплик между двумя метками?"
    )
