"""Сравнить готовый NLI-классификатор с ручной разметкой пар «реплика — утверждение»."""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np

from studio.semantic import DOC_ROLE
from studio.transcript import adjacent

REVISIONS = {
    "xsmall": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
    "small": "fa2804872c3b4bd748f38c0185cc85775361e735",
}

# Обе фразы в каждой паре составлены до запуска классификатора. Вторая добавляет или меняет факт.
PAIRS = [
    (
        1966,
        "The speaker would like to enter Aldrin in an oatmeal eating contest next time.",
        "Aldrin has won the oatmeal eating contest.",
    ),
    (
        7869,
        "The speaker had two cups of coffee with breakfast.",
        "The speaker had three cups of coffee with breakfast.",
    ),
    (
        1725,
        "The ground team plans to turn a blue-green laser on and off.",
        "The blue-green laser will be left on continuously.",
    ),
    (
        5290,
        "The material sticking to the speaker's boots was compared to powdered charcoal.",
        "The material sticking to the speaker's boots was compared to powdered sugar.",
    ),
    (
        4412,
        "The targeting system was taking them into a crater the size of a football field.",
        "The targeting system was taking them into a crater the size of a football.",
    ),
    (
        25,
        "The speaker was finally given a window to look out of.",
        "The speaker's window was taken away.",
    ),
    (
        4371,
        "People on the ground said that they were breathing again.",
        "People on the ground reported that they would never breathe again.",
    ),
    (
        472,
        "The speaker believes that California is two hundred years old.",
        "The speaker believes that Dr Mueller is two hundred years old.",
    ),
    (
        37,
        "The transmission sounded as clear as a conversation in a living room.",
        "The conversation actually took place inside Bruce's living room.",
    ),
    (
        8007,
        "The flight was described as a symbol of human curiosity about the unknown.",
        "The speaker said the flight was only about three men going to the Moon.",
    ),
]


INDEPENDENT_PAIRS = [
    (
        7432,
        "The speaker praises the chef and gives the cream of chicken soup at least three spoons.",
        "The speaker praises the chef and gives the cream of tomato soup at least three spoons.",
    ),
    (
        8207,
        "The speaker is drinking orange juice and asks for about five minutes.",
        "The speaker is drinking apple juice and asks for about five minutes.",
    ),
    (
        3592,
        "Houston recounts a legend about a rabbit standing on its hind legs in the shade of a cinnamon tree.",
        "The astronauts report seeing a rabbit on the Moon under a cinnamon tree with their own eyes.",
    ),
    (
        3592,
        "The name of the rabbit is not reported in the story.",
        "Houston reports that the rabbit's name is Jade.",
    ),
]


PRESS = [
    (
        7698,
        "The commander says his favorite album was made about twenty years ago.",
        "The commander says his favorite album was made yesterday.",
    ),
    (
        461,
        "Collins says they may be late answering because they are eating sandwiches.",
        "Collins says they may be late answering because they are still waiting for their sandwiches to arrive.",
    ),
    (
        7020,
        "Houston reports that after the landing the New York Times used the largest headlines in the newspaper's history.",
        "Houston reports that after the landing the New York Times used the smallest headlines in the newspaper's history.",
    ),
]

SUITES = {"original": PAIRS, "independent": INDEPENDENT_PAIRS, "press": PRESS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument(
        "model",
        nargs="?",
        type=Path,
        help="Локальный файл ONNX с config.json и tokenizer.json в каталоге модели",
    )
    origin.add_argument(
        "--download",
        action="store_true",
        help="Загрузить зафиксированную версию в кеш Hugging Face",
    )
    parser.add_argument("--size", choices=REVISIONS, default="xsmall")
    parser.add_argument(
        "--include-speaker",
        action="store_true",
        help="Передать роль говорящего вместе с репликой",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--suite", choices=SUITES, default="original")
    args = parser.parse_args()
    from onnxruntime import InferenceSession, SessionOptions, disable_telemetry_events
    from tokenizers import Tokenizer

    model_id = "cross-encoder/nli-deberta-v3-" + args.size
    revision = REVISIONS[args.size]
    model = args.model
    if args.download:
        from huggingface_hub import snapshot_download

        name = (
            "model_qint8_arm64.onnx"
            if platform.machine().lower() in {"arm64", "aarch64"}
            else "model.onnx"
        )
        root = Path(
            snapshot_download(
                model_id,
                revision=revision,
                allow_patterns=["config.json", "tokenizer.json", "onnx/" + name],
            )
        )
        model = root / "onnx" / name
    root = model.parent.parent if model.parent.name == "onnx" else model.parent
    config = json.loads((root / "config.json").read_text())
    tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=min(512, config["max_position_embeddings"]))
    tokenizer.enable_padding(pad_id=config["pad_token_id"])
    options = SessionOptions()
    disable_telemetry_events()
    options.intra_op_num_threads = 2
    session = InferenceSession(
        str(model), sess_options=options, providers=["CPUExecutionProvider"]
    )
    slots = {param.name for param in session.get_inputs()}
    rows = []
    for line_id, *claims in SUITES[args.suite]:
        row = adjacent(line_id, 0)
        passage = row["text"]
        if args.include_speaker:
            speaker = DOC_ROLE.get(row["speaker"].split(" ", 1)[0], row["speaker"])
            passage = f'{speaker} said, "{passage}"'
        encoded = tokenizer.encode_batch([(passage, claim) for claim in claims])
        features = {
            "input_ids": [e.ids for e in encoded],
            "attention_mask": [e.attention_mask for e in encoded],
            "token_type_ids": [e.type_ids for e in encoded],
        }
        logits = session.run(
            None,
            {
                k: np.asarray(v, dtype=np.int64)
                for k, v in features.items()
                if k in slots
            },
        )[0]
        scores = np.exp(logits - logits.max(axis=1, keepdims=True))
        scores /= scores.sum(axis=1, keepdims=True)
        for i, (claim, probs) in enumerate(zip(claims, scores, strict=True)):
            values = {
                config["id2label"][str(j)]: round(float(x), 5)
                for j, x in enumerate(probs)
            }
            verdict = max(values, key=values.get)
            supported = verdict == "entailment"
            rows.append(
                {
                    "line_id": line_id,
                    "page": row["page"],
                    "claim": claim,
                    "supported_by_source": i == 0,
                    "model_label": verdict,
                    "probabilities": values,
                    "correct": supported == (i == 0),
                }
            )
    with model.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    report = {
        "model": model_id,
        "revision": revision,
        "weights": model.name,
        "weights_sha256": digest,
        "speaker_included": args.include_speaker,
        **({"suite": args.suite} if args.suite != "original" else {}),
        "pair_source": "handwritten English hypotheses, gold source line supplied",
        "passed": sum(r["correct"] for r in rows),
        "total": len(rows),
        "false_confirmations": sum(
            r["model_label"] == "entailment" and not r["supported_by_source"]
            for r in rows
        ),
        "false_rejections": sum(
            r["model_label"] != "entailment" and r["supported_by_source"] for r in rows
        ),
        "cases": rows,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{report['passed']}/{report['total']}, ложных подтверждений {report['false_confirmations']}, пропущенных фраз {report['false_rejections']}"
    )
    for row in rows:
        if not row["correct"]:
            print(row["page"], row["claim"], row["model_label"])


if __name__ == "__main__":
    main()
