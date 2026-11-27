from studio import transcript_movement as movement
from studio.transcript import adjacent


def test_checked_source_phrases_belong_to_their_archive_lines():
    reviewed = movement.source_index()
    assert (
        5729 in reviewed and 6855 not in reviewed
    )  # «take into account» не описывает предмет.
    for line_id, transfers in reviewed.items():
        text = adjacent(line_id, 0)["text"]
        assert all(t.words in text for t in transfers)


def test_only_words_present_in_the_question_can_support_a_direction_mismatch():
    text = "Remove the equipment from the sleeping restraint under the right seat."
    result = movement.RequestedTransfer(
        verb="Remove",
        item="equipment",
        place="the sleeping restraint under the right seat",
        direction="from",
    )
    target = movement.question_transfer(result, text, {"from"})
    row = adjacent(8147, 0)
    found = movement.compare_indexed(target, row)
    assert found["source_words"] == "put it in the sleep restraint"
    assert (found["requested"], found["observed"]) == ("from", "into")
    assert not movement.question_transfer(result, text, {"into"})
    assert not movement.question_transfer(
        result.model_copy(update={"place": "the hidden drawer"}), text, {"from"}
    )
    no_motion = "Look at the equipment from the sleeping restraint."
    false_action = result.model_copy(
        update={"verb": "Look", "place": "the sleeping restraint"}
    )
    assert not movement.question_transfer(false_action, no_motion, {"from"})
    assert not movement.russian_directions("Они не просили вынуть оборудование?")


def test_other_objects_and_agreeing_directions_are_left_for_the_reader():
    source = adjacent(5589, 0)
    for text, item, direction in (
        ("Remove the camera from MESA", "camera", "from"),
        ("Put the notebook into MESA", "notebook", "into"),
    ):
        fact = movement.RequestedTransfer(
            verb=text.split()[0], item=item, place="MESA", direction=direction
        )
        facts = movement.question_transfer(fact, text, {direction})
        assert facts and movement.compare_indexed(facts, source) is None
