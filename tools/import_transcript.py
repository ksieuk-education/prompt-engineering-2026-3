"""Подготовить локальную копию страниц из OCR HTML, опубликованного NASA."""

import argparse
import gzip
import json
import re
from hashlib import sha256
from html import unescape
from pathlib import Path

SOURCE_SHA256 = "daf141a2c9030b0ca1e8748962af7a4cbfe227ed324f5c5ca085f063db271b3a"
# В издании встречаются GODS NET, Pa6e и слитное Tape74/8.
PAGE = re.compile(
    r"\(G[O0][SD][SD] NET 1\)\s*Tape\s*[\d/]+\s+Pa[g6]e\s+(\d+)", re.IGNORECASE
)
PARAGRAPH = re.compile(r"<br\s*/?>\s*<br\s*/?>", re.IGNORECASE)


def paragraphs(source: str) -> list[str]:
    blocks = []
    for block in PARAGRAPH.split(source):
        value = re.sub(r"<br\s*/?>|<hr\s*/?>", "\n", block, flags=re.IGNORECASE)
        value = unescape(re.sub(r"<[^>]+>", "", value)).replace("\xa0", " ")
        lines = [" ".join(line.split()) for line in value.splitlines() if line.strip()]
        if lines:
            blocks.append("\n".join(lines))
    return blocks


def convert(raw: bytes) -> dict:
    parts = PAGE.split(raw.decode("windows-1252"))
    page_numbers = [int(n) for n in parts[1::2]]
    if page_numbers != list(range(1, 625)):
        raise ValueError("Не удалось выделить подряд все 624 страницы этого издания.")
    return {
        page: paragraphs(part)
        for page, part in zip(page_numbers, parts[2::2], strict=True)
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.html.read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        parser.error("Контрольная сумма отличается от проверенной редакции NASA.")
    data = json.dumps(convert(raw), ensure_ascii=False, separators=(",", ":")).encode()
    args.output.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    print(f"Подготовлены 624 страницы, файл {args.output.stat().st_size:,} байт.")


if __name__ == "__main__":
    main()
