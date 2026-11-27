"""Необязательный локальный перевод запросов готовой моделью Argos ru → en."""

import re
from functools import lru_cache
from pathlib import Path

from .transcript_evidence import SEARCH_WORDS

QUERY_WORDS = SEARCH_WORDS | {
    "according",
    "call",
    "called",
    "can",
    "could",
    "describe",
    "described",
    "did",
    "do",
    "does",
    "eleven",
    "get",
    "how",
    "locate",
    "me",
    "mentioned",
    "mentions",
    "message",
    "number",
    "out",
    "phrase",
    "place",
    "please",
    "read",
    "recorded",
    "saying",
    "someone",
    "something",
    "space",
    "talked",
    "talking",
    "talks",
    "tell",
    "there",
    "transcripts",
    "us",
    "we",
    "when",
    "who",
}


@lru_cache(maxsize=1)
def engine(directory: str):
    import ctranslate2
    import sentencepiece

    folder = Path(directory)
    tokenizer = sentencepiece.SentencePieceProcessor(
        model_file=str(folder / "sentencepiece.model")
    )
    translator = ctranslate2.Translator(
        str(folder / "model"),
        device="cpu",
        compute_type="int8",
        intra_threads=2,
        inter_threads=1,
    )
    return tokenizer, translator


def queries(question: str, directory: str) -> list[str]:
    tokenizer, translator = engine(directory)
    tokens = tokenizer.encode(question, out_type=str)
    result = translator.translate_batch(
        [tokens], beam_size=3, max_input_length=280, max_decoding_length=160
    )
    english = tokenizer.decode(result[0].hypotheses[0]).strip()
    content = dict.fromkeys(
        word
        for word in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", english.lower())
        if len(word) > 2 and word not in QUERY_WORDS
    )
    keywords = " ".join(list(content)[:8])[:85]
    return list(dict.fromkeys(q for q in (english[:160], keywords) if q))
