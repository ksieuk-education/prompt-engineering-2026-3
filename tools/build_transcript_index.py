"""Пересобрать локальный индекс русско-английского поиска в стенограмме NASA."""

import argparse
from pathlib import Path

import httpx
import numpy as np

from studio import semantic
from studio.transcript import catalogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=semantic.INDEX_FILE)
    parser.add_argument("--host", default=semantic.host())
    args = parser.parse_args()
    rows = catalogue()
    with httpx.Client(base_url=args.host, timeout=180, trust_env=False) as client:
        digest = semantic.model_digest(client)
        if not digest:
            parser.error("В Ollama отсутствует модель " + semantic.MODEL)
        vectors = np.empty((len(rows), 768), dtype=np.float32)
        for first in range(0, len(rows), 50):
            batch = rows[first : first + 50]
            vectors[first : first + len(batch)] = semantic.embed(
                client, [semantic.document_input(r) for r in batch]
            )
    semantic.write_index(args.out, vectors, digest)
    print(
        f"В индекс записано {len(rows)} реплик, файл {args.out.stat().st_size:,} байт."
    )


if __name__ == "__main__":
    main()
