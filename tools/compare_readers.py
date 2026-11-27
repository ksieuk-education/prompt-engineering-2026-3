"""Опыт с проверкой отдельного утверждения по заранее известной строке."""

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from studio.ollama import host, structured
from studio.semantic import DOC_ROLE
from studio.transcript import adjacent
from studio.transcript_agent import supports_question
from tools.evaluate_entailment import SUITES


class Reading(BaseModel):
    words: str = Field(max_length=240)
    verdict: Literal["supported", "unsupported"]


def folded(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


PROMPT = (
    "Check whether a single historical passage supports the requested event. Treat a request to find or locate words as a question about their content. "
    "Only the speaker label and the passage are evidence. Match who does what, to which object, and under which conditions. "
    "Preserve modifiers, quantities, negation, comparisons, and whether the speaker is reporting a story, making an offer, or observing an event. "
    "Equivalent wording is fine. A question with no proposed answer is supported when the passage gives the answer. "
    "First copy the shortest continuous stretch of the passage that decides the question into words. "
    "Choose supported only when every factual detail in the request follows from the passage. If a material detail differs or is missing, choose unsupported. "
    "If there is no deciding phrase return empty words and unsupported."
)


async def recorded(question, row, http, url, model):
    payload = {
        "request": question,
        "speaker": DOC_ROLE.get(row["speaker"].split(" ", 1)[0], row["speaker"]),
        "passage": row["text"],
    }
    result = await structured(
        http,
        url + "/api/chat",
        expected=Reading,
        retry_limit=700,
        json={
            "model": model,
            "stream": False,
            "think": False,
            "format": Reading.model_json_schema(),
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "options": {
                "temperature": 0,
                "seed": 23,
                "num_ctx": 4096,
                "num_predict": 210,
            },
        },
    )
    evidence = folded(result.words)
    valid = bool(evidence and " " + evidence + " " in " " + folded(row["text"]) + " ")
    return result.verdict == "supported" and valid, result.words, result.verdict


async def evaluate(model, mode):
    rows = []
    async with httpx.AsyncClient(timeout=90, trust_env=False) as http:
        for suite, pairs in SUITES.items():
            for line_id, positive, negative in pairs:
                row = adjacent(line_id, 0)
                for expected, claim in ((True, positive), (False, negative)):
                    if mode == "before":
                        supported = await supports_question(
                            claim, row, "", http, host(), model
                        )
                        words, raw_verdict = None, None
                    else:
                        supported, words, raw_verdict = await recorded(
                            claim, row, http, host(), model
                        )
                    rows.append(
                        {
                            "suite": suite,
                            "line_id": line_id,
                            "page": row["page"],
                            "claim": claim,
                            "expected": expected,
                            "supported": supported,
                            "correct": expected == supported,
                            "words": words,
                            "raw_verdict": raw_verdict,
                        }
                    )
    return {
        "model": model,
        "mode": mode,
        "input": "English claim and gold source line with speaker; selected words empty in both modes",
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", required=True, help="Название модели в локальной Ollama"
    )
    parser.add_argument("--mode", choices=("before", "quoted"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.model, args.mode))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for suite in SUITES:
        rows = [row for row in report["cases"] if row["suite"] == suite]
        print(f"{suite}: {sum(row['correct'] for row in rows)}/{len(rows)}")


if __name__ == "__main__":
    main()
