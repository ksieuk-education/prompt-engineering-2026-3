"""Измерить ранг нужного фрагмента до проверки цитаты языковой моделью."""

import argparse
import json
from pathlib import Path

import httpx
import numpy as np

from studio import semantic
from studio.transcript import catalogue
from tools.evaluate import PARAPHRASES, matches_paraphrase


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host", default=semantic.host())
    args = parser.parse_args()
    digest, matrices = semantic.open_index()
    with httpx.Client(base_url=args.host, timeout=120, trust_env=False) as client:
        if semantic.model_digest(client) != digest:
            parser.error(
                "Нужна та же версия EmbeddingGemma, что и при построении индекса."
            )
        prompts = [
            "task: search result | query: " + q for q, _, _ in PARAPHRASES.values()
        ]
        encoded = semantic.embed(client, prompts)
    records = catalogue()
    output = []
    for matrix in matrices:
        dims = matrix.shape[1]
        scores = semantic.unit(encoded[:, :dims]) @ matrix.T
        for (key, (question, page, _)), values in zip(
            PARAPHRASES.items(), scores, strict=True
        ):
            order = np.argsort(-values, kind="stable")
            rank = next(
                (
                    pos
                    for pos, idx in enumerate(order, 1)
                    if page and matches_paraphrase(key, records[idx])
                ),
                None,
            )
            top = [
                {k: records[idx][k] for k in ("id", "page", "get")}
                | {"score": round(float(values[idx]), 4)}
                for idx in order[:5]
            ]
            output.append(
                {
                    "dimensions": dims,
                    "id": key,
                    "question": question,
                    "gold_rank": rank,
                    "top5": top,
                }
            )
            print(dims, key, rank, top[0]["page"], top[0]["score"])
    report = {
        "model": semantic.MODEL,
        "model_digest": digest,
        "corpus_size": len(records),
        "queries": output,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
