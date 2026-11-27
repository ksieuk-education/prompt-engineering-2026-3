"""Поиск кандидатов в англоязычной стенограмме по русскому описанию."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from .archive import ROOT
from .ollama import host
from .transcript import catalogue, index
from .transcript_evidence import SEARCH_WORDS, source_hints

MODEL = "embeddinggemma:300m"
INDEX_FILE = ROOT / "data/field/transcript-vectors.npz"
DOC_ROLE = {
    "CDR": "Neil Armstrong",
    "LMP": "Buzz Aldrin",
    "CMP": "Michael Collins",
    "CC": "Houston CAPCOM",
}


def document_input(row):
    code = row["speaker"].split(" ", 1)[0]
    return (
        "title: "
        + DOC_ROLE.get(code, row["speaker"] or "none")
        + " | text: "
        + row["text"]
    )


def corpus_digest():
    values = [(r["speaker"], r["text"]) for r in catalogue()]
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def embed(client, texts):
    response = client.post(
        "/api/embed", json={"model": MODEL, "input": texts, "truncate": False}
    )
    response.raise_for_status()
    arr = np.asarray(response.json()["embeddings"], dtype=np.float32)
    if arr.shape != (len(texts), 768) or not np.isfinite(arr).all():
        raise ValueError("Модель вернула вектор с неожиданной размерностью.")
    return arr


def model_digest(client):
    models = client.get("/api/tags").raise_for_status().json()["models"]
    return next((m["digest"] for m in models if m["name"] == MODEL), "")


def write_index(path: Path, vectors: np.ndarray, digest: str):
    quantized = np.rint(
        127 * vectors / np.maximum(np.abs(vectors).max(axis=1, keepdims=True), 1e-12)
    ).astype(np.int8)
    # Новая копия становится видна только после успешной записи всего индекса.
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(dir=path.parent, delete=False, suffix=".npz") as tmp:
        scratch = Path(tmp.name)
    try:
        np.savez_compressed(
            scratch,
            vectors=quantized,
            model_digest=digest,
            corpus_digest=corpus_digest(),
        )
        scratch.replace(path)
    finally:
        scratch.unlink(missing_ok=True)


def unit(rows):
    return rows / np.maximum(np.linalg.norm(rows, axis=1, keepdims=True), 1e-12)


@lru_cache(maxsize=1)
def open_index():
    with np.load(INDEX_FILE, allow_pickle=False) as bundle:
        matrix = bundle["vectors"]
        if (
            matrix.dtype != np.int8
            or matrix.shape != (len(catalogue()), 768)
            or bundle["corpus_digest"].item() != corpus_digest()
        ):
            raise ValueError("Индекс не соответствует изданию стенограммы.")
        digest = bundle["model_digest"].item()
    return digest, [unit(matrix[:, :size].astype(np.float32)) for size in (256, 768)]


def lexical_candidates(queries):
    groups = []
    examined = set()
    for query in queries:
        words = list(
            dict.fromkeys(
                w
                for w in re.findall(r"[a-z0-9]+", query.lower())
                if w not in SEARCH_WORDS
            )
        )
        if not words:
            continue
        expression = " OR ".join(f'"{word}"' for word in words[:12])
        rows = index().execute(
            "SELECT rowid FROM speech WHERE speech MATCH ? ORDER BY rank, rowid LIMIT 12",
            (expression,),
        )
        groups.append([x for (x,) in rows])
        for word in words[:14]:
            if word in examined:
                continue
            examined.add(word)
            isolated = (
                index()
                .execute(
                    "SELECT rowid FROM speech WHERE speech MATCH ? LIMIT 4",
                    (f'"{word}"',),
                )
                .fetchall()
            )
            if 0 < len(isolated) <= 3:
                groups.append([item[0] for item in isolated])
    return groups


def ranked_candidates(
    question: str, queries: list[str], page: int | None = None
) -> dict:
    queries = [q[:160] for q in queries[:2] if q.strip()]
    if page is not None:
        # На одной печатной странице максимум 24 строки; все помещаются в контекст чтения.
        rows = [row for row in catalogue() if row["page"] == page]
        return {
            "mode": "page",
            "candidates": rows,
            "hints": source_hints(queries, rows),
        }
    groups = lexical_candidates(queries)
    mode = "fts"
    if INDEX_FILE.is_file():
        try:
            digest, matrices = open_index()
            with httpx.Client(base_url=host(), timeout=40, trust_env=False) as client:
                if model_digest(client) == digest:
                    inputs = [
                        "task: search result | query: " + s
                        for s in [question, *queries]
                    ]
                    encoded = embed(client, inputs)
                    for matrix in matrices:
                        scores = unit(encoded[:, : matrix.shape[1]]) @ matrix.T
                        groups.extend(
                            (np.argsort(-row, kind="stable")[:16] + 1).tolist()
                            for row in scores
                        )
                    mode = "fts+embeddinggemma"
        except (httpx.HTTPError, ValueError, OSError, KeyError):
            # Поиск по словам работает и без модели эмбеддингов или ее совместимого индекса.
            pass
    weights = {}
    for group in groups:
        for rank, line_id in enumerate(group):
            weights[line_id] = weights.get(line_id, 0) + 1 / (6 + rank)
    # Сохраняем лучшие строки каждого способа, затем заполняем места по сумме обратных рангов.
    head = [
        item
        for group in groups
        if group
        for item in (group if len(group) <= 3 else group[:1])
    ]
    ordering = sorted(weights, key=weights.get, reverse=True)
    selected = list(dict.fromkeys([*head, *ordering]))[:14]
    rows = [catalogue()[i - 1] for i in selected]
    return {"mode": mode, "candidates": rows, "hints": source_hints(queries, rows)}
