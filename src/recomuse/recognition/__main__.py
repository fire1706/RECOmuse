"""Essai de la reconnaissance en ligne de commande (outil de développement).

    python -m recomuse.recognition partition.pdf [--out DOSSIER] [--pages 1-3]

Importe le fichier (tâche 3), lance Audiveris et Tesseract, puis affiche ce qui a été
reconnu. Les fichiers d'origine ne sont jamais modifiés.
"""

import argparse
import sys
import time
from pathlib import Path

from recomuse import paths
from recomuse.importer import ScoreImportError, import_score
from recomuse.recognition.audiveris import AudiverisError
from recomuse.recognition.pipeline import recognize_score
from recomuse.recognition.tools import ToolNotFoundError, check_tools


def parse_page_range(text: str) -> tuple[int, int]:
    """« 3 » → (3, 3) ; « 1-4 » → (1, 4)."""
    first, _, last = text.partition("-")
    return int(first), int(last or first)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recomuse.recognition")
    parser.add_argument("file", type=Path, help="PDF ou image à reconnaître")
    parser.add_argument("--out", type=Path, default=None, help="dossier de travail")
    parser.add_argument("--pages", type=parse_page_range, default=None,
                        help="pages à reconnaître, ex. 1-3 (toutes par défaut)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    status = check_tools()
    print(f"Audiveris : {status.audiveris or 'INTROUVABLE'}")
    print(f"Tesseract : {status.tesseract or 'INTROUVABLE'}")
    print(f"Langues   : {', '.join(status.languages) or 'aucune'}"
          + (f" (manquantes : {', '.join(status.missing_languages)})"
             if status.missing_languages else ""))

    work_dir = (args.out or paths.imports_dir()) / args.file.stem
    try:
        score = import_score(args.file, work_dir)
    except ScoreImportError as error:
        print(f"ÉCHEC de l'import : {error.code} {error.detail}")
        return 1
    if args.pages:
        first, last = args.pages
        score.pages = [p for p in score.pages if first <= p.page_number <= last]

    last_shown = [-1]

    def show_progress(done: int, total: int) -> None:
        percent = 100 * done // total
        if percent >= last_shown[0] + 10:
            last_shown[0] = percent
            print(f"  ... {percent} %", flush=True)

    start = time.perf_counter()
    try:
        result = recognize_score(score, on_progress=show_progress)
    except (ToolNotFoundError, AudiverisError) as error:
        print(f"ÉCHEC de la reconnaissance : {error.code}")
        return 1

    header = result.header
    print(f"\nTerminé en {time.perf_counter() - start:.0f} s "
          f"(Audiveris {result.run.duration_seconds:.0f} s), "
          f"{len(result.run.book.sheet_pages)} page(s) de musique : {result.run.book.sheet_pages}")
    print(f"Titre      : {header.title}")
    print(f"Instrument : {header.instrument}")
    print(f"Tempo      : {header.tempo}")
    print(f"Auteurs    : {' / '.join(header.composers)}")
    if header.other:
        print(f"Autres     : {' / '.join(header.other)}")
    print(f"Mesures    : {result.measure_count} en {len(result.movements)} mouvement(s)")
    for movement in result.movements:
        print(f"  {movement.path.name}: page(s) {result.movement_pages(movement)}, "
              f"systèmes {movement.sheet_systems}, "
              f"{movement.measure_count} mesures, chiffrages {movement.time_signatures}, "
              f"parties {movement.part_names}")
    if result.vector and result.vector.pages:
        v = result.vector
        print(f"Lecture vectorielle : {v.measure_count()} mesures, chiffrages {v.time_changes()}, "
              f"armures {v.key_changes()}, pauses multiples {v.multirests()}, "
              f"durées fausses {v.duration_mismatches()}")
    if result.warnings:
        print(f"ATTENTION: {', '.join(result.warnings)}")
    print(f"-> {result.run.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
