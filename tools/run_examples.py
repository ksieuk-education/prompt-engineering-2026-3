"""Повторить шесть живых вопросов. Сначала запустите python -m studio."""

import argparse
import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

# Независимый ключ к шести фиксированным вопросам. Сам агент его не получает.
REFERENCE = json.loads((ROOT / "tools/control.json").read_text())


def check_answers(case_id, turns):
    expected = REFERENCE[case_id]["measurement"]
    passages = set(REFERENCE[case_id]["facts"])
    if len(turns) != 2 or any(turn["status"] != "answered" for turn in turns):
        raise ValueError(f"{case_id}: требуется два подтвержденных ответа")
    first, follow_up = turns
    readings = first["measurements"]
    if len(readings) != 1 or any(
        readings[0].get(key) != value for key, value in expected.items()
    ):
        raise ValueError(
            f"{case_id}: измерение расходится с независимой сверкой документов"
        )
    if not passages.intersection(follow_up["passages"]):
        raise ValueError(
            f"{case_id}: в уточнении отсутствует подтверждение из первоисточника"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default="http://127.0.0.1:" + os.getenv("ARCHIVE_PORT", "8765")
    )
    parser.add_argument("--out", type=Path, default=ROOT / "examples")
    parser.add_argument("--case", choices=["signal", "splice", "untimed"])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, timeout=600, trust_env=False) as client:
        listing = client.get("/api/cases")
        listing.raise_for_status()
        for case in listing.json():
            if args.case and case["id"] != args.case:
                continue
            session = client.post("/api/sessions", json={"case_id": case["id"]})
            session.raise_for_status()
            turns = []
            for question in case["questions"]:
                response = client.post(
                    "/api/ask",
                    json={"session": session.json()["session"], "question": question},
                )
                response.raise_for_status()
                turn = response.json()
                print(
                    case["id"],
                    turn["status"],
                    turn["answer"],
                    [s["tool"] for s in turn["steps"]],
                    flush=True,
                )
                if turn["status"] != "answered":
                    raise RuntimeError("Ответ не прошел проверку источников.")
                turns.append(turn)
            check_answers(case["id"], turns)
            destination = args.out / (case["id"] + ".json")
            tmp = destination.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {"case": case["id"], "model": turns[0]["model"], "turns": turns},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            tmp.replace(destination)


if __name__ == "__main__":
    main()
