"""Essai de l'import en ligne de commande (outil de développement).

    python -m recomuse.importer partition.pdf [autre.png ...] [--out DOSSIER]

Pour chaque fichier : affiche le type de chaque page et les mesures trouvées,
et enregistre les pages prêtes dans DOSSIER (par défaut, le dossier des imports
dans les données locales). Les fichiers d'origine ne sont jamais modifiés.
"""

import argparse
import sys
import time
from pathlib import Path

from recomuse import paths
from recomuse.importer import ScoreImportError, import_score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recomuse.importer")
    parser.add_argument("files", nargs="+", type=Path, help="PDF ou images à importer")
    parser.add_argument("--out", type=Path, default=None,
                        help="dossier où écrire les pages préparées")
    args = parser.parse_args(argv)
    # La console Windows ne sait pas toujours afficher tous les caractères :
    # on remplace ceux qu'elle ne connaît pas au lieu de s'arrêter sur une erreur.
    sys.stdout.reconfigure(errors="replace")

    out_root = args.out or paths.imports_dir()
    failures = 0
    for source in args.files:
        start = time.perf_counter()
        try:
            score = import_score(source, out_root / source.stem)
        except ScoreImportError as error:
            print(f"ÉCHEC  {source.name} : {error.code} {error.detail}")
            failures += 1
            continue

        elapsed = time.perf_counter() - start
        print(f"{source.name} : {score.source_kind}, {score.page_count} page(s), {elapsed:.1f} s")
        for page in score.pages:
            print(
                f"  p.{page.page_number:<3} {page.kind:8}"
                f" origine={page.source_dpi or '-'} dpi"
                f" rotation={page.rotation_degrees:+.2f}°"
                f" interligne={page.interline or '-'} épaisseur={page.line_thickness or '-'}"
                + (f" polices={','.join(page.music_fonts)}" if page.music_fonts else "")
                + (f" ATTENTION: {','.join(page.warnings)}" if page.warnings else "")
            )
        print(f"  -> {score.work_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
