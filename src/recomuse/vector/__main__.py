"""Essai de la lecture vectorielle en ligne de commande (outil de développement).

    python -m recomuse.vector partition.pdf [--pages 1-3] [--part 0] [--notes]

Affiche, pour la partie choisie (rang de la portée dans le système), les mesures,
changements de chiffrage et d'armure, pauses multiples ; avec --notes, les notes
de chaque mesure. Le fichier n'est jamais modifié.
"""

import argparse
import sys
import time
from pathlib import Path

from recomuse.recognition.__main__ import parse_page_range
from recomuse.vector import read_vector_pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recomuse.vector")
    parser.add_argument("file", type=Path)
    parser.add_argument("--pages", type=parse_page_range, default=None)
    parser.add_argument("--part", type=int, default=0, help="rang de la portée (0 = la 1re)")
    parser.add_argument("--notes", action="store_true", help="affiche les notes de chaque mesure")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    start = time.perf_counter()
    pages = list(range(args.pages[0], args.pages[1] + 1)) if args.pages else None
    score = read_vector_pdf(args.file, pages)
    elapsed = time.perf_counter() - start

    print(f"{args.file.name} : {len(score.pages)} page(s) vectorielle(s) lue(s) en {elapsed:.1f} s, "
          f"{score.staff_count} portée(s) par système")
    if not score.pages:
        print(f"Aucune page lisible. {', '.join(score.warnings)}")
        return 1
    print(f"Mesures         : {score.measure_count(args.part)}")
    print(f"Chiffrages      : {score.time_changes(args.part)}")
    print(f"Armures         : {score.key_changes(args.part)}")
    print(f"Pauses multiples: {score.multirests(args.part)}")
    if score.warnings:
        print(f"ATTENTION: {', '.join(score.warnings)}")
    if args.notes:
        for item in score.part_measures(args.part):
            m = item.measure
            content = " ".join(n.name or n.head for n in m.notes)
            extra = []
            if m.clef:
                extra.append(f"clé {m.clef}")
            if m.key_fifths is not None:
                extra.append(f"armure {m.key_fifths:+d}")
            if m.time_signature:
                extra.append(m.time_signature)
            if m.is_multirest:
                extra.append(f"pause x{m.multirest}")
            if m.full_rest:
                extra.append("pause")
            if m.printed_number is not None:
                extra.append(f"n° imprimé {m.printed_number}")
            rests = " ".join(r.value for r in m.rests)
            print(f"  m{item.number:<4} p{item.page} s{item.system} [{', '.join(extra)}] "
                  f"{content}" + (f" | silences: {rests}" if rests and not m.full_rest else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
