"""Copie les programmes externes à embarquer dans l'installateur (dossier build/tools).

Windows : Audiveris (avec son Java), Tesseract (programme et bibliothèques, sans les outils
d'entraînement ni la documentation) et les 4 langues de Tesseract utilisées par RECOmuse.
Chacun est cherché là où RECOmuse le trouve lui-même (recognition/tools.py) : la machine
de construction doit donc avoir Audiveris, Tesseract et les langues installés.

Usage :  python packaging/prepare_tools.py [dossier de sortie]
"""

import shutil
import sys
from pathlib import Path

from recomuse.recognition import tools

# Programmes de Tesseract à garder (les autres servent à entraîner de nouvelles langues).
TESSERACT_PROGRAMS = {"tesseract.exe"}


def copy_audiveris(target: Path) -> None:
    exe = tools.find_audiveris()
    if exe is None:
        raise SystemExit("Audiveris est introuvable sur cette machine.")
    source = exe.parent
    print(f"Audiveris : {source}")
    shutil.copytree(source, target / "Audiveris", dirs_exist_ok=True)


def copy_tesseract(target: Path) -> None:
    exe = tools.find_tesseract()
    if exe is None:
        raise SystemExit("Tesseract est introuvable sur cette machine.")
    source = exe.parent
    print(f"Tesseract : {source}")
    destination = target / "Tesseract-OCR"
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        keep = item.suffix.lower() == ".dll" or item.name.lower() in TESSERACT_PROGRAMS \
            or item.name.lower().startswith(("license", "copying"))
        if item.is_file() and keep:
            shutil.copy2(item, destination / item.name)


def copy_tessdata(target: Path) -> None:
    folder = tools.find_tessdata()
    if folder is None:
        raise SystemExit("Les langues de Tesseract sont introuvables.")
    missing = [lang for lang in tools.OCR_LANGUAGES
               if not (folder / f"{lang}.traineddata").is_file()]
    if missing:
        raise SystemExit(f"Langues de Tesseract manquantes : {missing}")
    print(f"Langues de Tesseract : {folder}")
    destination = target / tools.TESSDATA_DIRNAME
    destination.mkdir(parents=True, exist_ok=True)
    for lang in tools.OCR_LANGUAGES:
        shutil.copy2(folder / f"{lang}.traineddata", destination)
    # osd : orientation des pages, demandé par Audiveris s'il est présent.
    if (folder / "osd.traineddata").is_file():
        shutil.copy2(folder / "osd.traineddata", destination)


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build") / "tools"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    copy_audiveris(target)
    copy_tesseract(target)
    copy_tessdata(target)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1e6
    print(f"Outils prêts dans {target} ({size:.0f} Mo)")


if __name__ == "__main__":
    main()
