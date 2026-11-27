"""Проверить распознавание обратного движения предмета отдельно от поиска по архиву."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

from studio.archive import ROOT
from studio.transcript_movement import difference, events, pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="en_core_web_sm")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    nlp = pipeline(args.model)
    cases = json.loads((ROOT / "tools/movement_controls.json").read_text())
    results = []
    for case in cases:
        question, source = nlp.pipe((case["request"], case["passage"]))
        found = difference(events(question), events(source))
        results.append(
            {**case, "difference": found, "passed": bool(found) == case["opposite"]}
        )
    report = {
        "spacy": version("spacy"),
        "model": args.model,
        "model_version": nlp.meta["version"],
        "source": "https://spacy.io/models/en/#en_core_web_sm",
        "task": "Identify an explicitly opposite direction in the cited line for the same item and location. Other events remain unknown.",
        "passed": sum(row["passed"] for row in results),
        "total": len(results),
        "cases": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{report['passed']}/{report['total']}")


if __name__ == "__main__":
    main()
