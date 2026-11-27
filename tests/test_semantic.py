import numpy as np

from studio import semantic
from studio.transcript import catalogue, search_transcript
from studio.transcript_evidence import (
    compare_quantities,
    quantity_difference,
    source_hints,
    supports_vocabulary,
)


def test_index_is_bound_to_the_same_edition_and_speakers():
    digest, (short, full) = semantic.open_index()
    assert len(digest) == 64
    assert short.shape == (len(catalogue()), 256)
    assert full.shape == (len(catalogue()), 768)
    assert np.allclose(np.linalg.norm(short[::100], axis=1), 1, atol=1e-5)
    assert semantic.document_input(catalogue()[0]).startswith(
        "title: Neil Armstrong | text: "
    )


def test_word_search_remains_available_without_vector_index(tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "INDEX_FILE", tmp_path / "absent.npz")
    result = semantic.ranked_candidates("Позывной после посадки", ["eagle landed"])
    assert result["mode"] == "fts"
    assert any(row["page"] == 317 for row in result["candidates"])


def test_distinctive_words_are_copied_from_source_and_absent_terms_do_not_confirm_colour():
    laser = search_transcript("blue-green laser", exact=True)["matches"][0]
    hits = source_hints(["a blue green laser", "blue green laser"], [laser])
    assert hits["anchors"] == [{"id": laser["id"], "quote": "blue-green laser"}]
    assert supports_vocabulary(hits, laser["text"])
    unrelated = source_hints(["giraffe silhouette resilience"], [laser])
    assert len(unrelated["missing_keywords"]) == 3 and not unrelated["anchors"]
    assert not supports_vocabulary(unrelated, "It is bluish-green.")


def test_count_check_needs_both_languages_and_the_same_counted_item():
    wanted = "He had three cups of coffee."
    assert quantity_difference(
        "Пил три чашки?", wanted, "I had two cups of coffee."
    ) == {"requested": 3, "printed": 2, "words": "two cups of coffee"}
    for passage in (
        "I had three cups of coffee.",
        "Two cups of tea.",
        "We had two or three cups of coffee.",
        "At least two cups of coffee.",
        "Two cups of coffee, then three cups of coffee.",
    ):
        assert quantity_difference("Пил три чашки?", wanted, passage) is None
    assert quantity_difference("Пил две чашки?", wanted, "Two cups of coffee.") is None
    assert (
        quantity_difference("Это 4 батареи?", "four batteries", "six batteries")[
            "printed"
        ]
        == 6
    )


def test_equal_counts_from_another_meal_cannot_confirm_a_breakfast():
    made = catalogue()[1212 - 1]
    breakfast = catalogue()[7869 - 1]
    question = "За завтраком с персиками выпили три чашки кофе?"
    queries = [
        "During breakfast with peaches, the astronaut drank three cups of coffee.",
        "breakfast peaches coffee",
    ]
    differences, other_events, best = compare_quantities(
        question, queries, [made, breakfast]
    )
    assert differences[7869]["printed"] == 2 and other_events == {1212} and best == 7869
    assert (
        compare_quantities(
            "Сделали три чашки кофе?", ["made three cups of coffee"], [made, breakfast]
        )[1]
        == set()
    )


def test_single_folio_provides_all_its_readable_rows_without_embeddings():
    result = semantic.ranked_candidates(
        "лунные образцы", ["sample return containers"], page=544
    )
    assert result["mode"] == "page" and len(result["candidates"]) == 14
    assert {r["page"] for r in result["candidates"]} == {544}
    assert any(r["id"] == 7542 for r in result["candidates"])
