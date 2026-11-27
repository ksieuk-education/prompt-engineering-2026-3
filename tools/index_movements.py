"""Разметить в источнике явные действия перемещения готовой английской моделью spaCy."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path
from tempfile import NamedTemporaryFile

from studio.archive import ROOT
from studio.semantic import corpus_digest
from studio.transcript import catalogue
from studio.transcript_movement import events, pipeline


def build(output: Path, name: str):
    model = pipeline(name)
    rows = catalogue()
    actions = {}
    for row, doc in zip(
        rows, model.pipe((r["text"] for r in rows), batch_size=64), strict=True
    ):
        transfers = events(doc)
        if transfers:
            actions[str(row["id"])] = [
                {
                    "direction": t.direction,
                    "place": t.place,
                    "modifiers": sorted(t.modifiers),
                    "items": sorted(t.items),
                    "words": t.words,
                }
                for t in transfers
            ]
    result = {
        "model": name,
        "model_version": model.meta["version"],
        "spacy": version("spacy"),
        "source": "https://spacy.io/models/en/#en_core_web_sm",
        "corpus_sha256": corpus_digest(),
        "lines_scanned": len(rows),
        "lines_with_actions": len(actions),
        "actions": actions,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=output.parent, suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as f:
        tmp = Path(f.name)
        try:
            f.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            f.flush()
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    return len(actions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="en_core_web_sm")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "data/field/transcript-movements.json"
    )
    args = parser.parse_args()
    print(f"Строк с размеченными действиями — {build(args.out, args.model)}.")


if __name__ == "__main__":
    main()
