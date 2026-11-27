"""Сохраненные прогоны модели соответствуют независимому разбору трех дел."""

import json

import pytest

from studio.archive import CASES, ROOT
from tools.run_examples import check_answers


@pytest.mark.parametrize("case_id", list(CASES))
def test_recorded_conversation(case_id):
    sample = json.loads((ROOT / "examples" / f"{case_id}.json").read_text())
    assert sample["case"] == case_id
    turns = sample["turns"]
    check_answers(case_id, turns)
    valid_ids = {doc["id"] for doc in CASES[case_id]["documents"]}
    for question, turn in zip(CASES[case_id]["questions"], turns, strict=True):
        assert turn["question"] == question
        assert turn["sources"] and set(turn["sources"]) <= valid_ids
        assert all(key.split(".")[0] in turn["sources"] for key in turn["passages"])
