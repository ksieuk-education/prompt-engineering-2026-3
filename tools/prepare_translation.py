"""Скачать или распаковать проверенную офлайн-модель Argos ru → en 1.9."""

import argparse
import hashlib
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

URL = "https://data.argosopentech.com/argospm/v1/translate-ru_en-1_9.argosmodel"
SHA256 = "e9ba8bf722d10a4a4c39f74289d5938fd47eac08dbe4ed0afd22d89445a5c3ac"
FILES = {
    "README.md": "5a157fd062b9786eb4c7d5aa8fce0f3f01de0fa71c2f34fbf16e222c66ecd090",
    "metadata.json": "2034d666010673068722bc15af5bb8561173665872867c89a1b99695f0fb25d0",
    "sentencepiece.model": "d324f59d3b5ba04d9b088e162b5e779e27a5eb72d56ec8e5e69a9efc1bf8f495",
    "model/config.json": "3f1a3cc20b961c1fe0e6007e8ca663730c4a8b82fa54073fde03edf1402c6726",
    "model/model.bin": "026d5f34266b4235c13fc29c665f151b88d0c1b02b0be7f87734fe9c511e20bc",
    "model/shared_vocabulary.json": "32d134b048b6a27a48ba7fad9154976743b9bed9cbef7080b952108374d1cea1",
}


def digest(file: Path) -> str:
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def complete(folder: Path) -> bool:
    return all(
        (folder / name).is_file() and digest(folder / name) == sha
        for name, sha in FILES.items()
    )


def prepare(destination: Path, package: Path | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if complete(destination):
            return
        raise ValueError(
            f"Путь {destination} уже существует. Укажите новый каталог для модели."
        )
    with TemporaryDirectory(dir=destination.parent) as temporary:
        work = Path(temporary)
        if package is None:
            package = work / "model.argosmodel"
            with urlopen(URL, timeout=60) as remote, package.open("wb") as local:
                shutil.copyfileobj(remote, local)
        if digest(package) != SHA256:
            raise ValueError(
                "Контрольная сумма пакета отличается от опубликованной в лабораторной."
            )
        ready = work / "ready"
        with ZipFile(package) as archive:
            for name in FILES:
                target = ready / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open("translate-ru_en-1_9/" + name) as src,
                    target.open("wb") as dst,
                ):
                    shutil.copyfileobj(src, dst)
        if not complete(ready):
            raise ValueError("Не удалось проверить извлеченные файлы модели.")
        try:
            ready.rename(destination)
        except OSError:
            if not complete(destination):
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--package", type=Path, help="Уже скачанный файл .argosmodel")
    args = parser.parse_args()
    prepare(args.out, args.package)
    print(f"Модель Argos готова в {args.out.resolve()}")


if __name__ == "__main__":
    main()
