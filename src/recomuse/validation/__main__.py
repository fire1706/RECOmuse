"""Essai du validateur en ligne de commande (outil de développement).

    python -m recomuse.validation partition.pdf [--pages 1-2] [--audiveris] [--detail]
    python -m recomuse.validation parties.pdf [autre.pdf...] --compare

Importe, reconnaît, construit le modèle puis le valide, et affiche les problèmes trouvés.
--audiveris : fait lire les pages vectorielles par Audiveris (au lieu de la lecture
vectorielle exacte), pour voir ce que le validateur trouve dans les erreurs d'Audiveris.
--compare : sépare les parties de chaque fichier (un PDF peut les contenir toutes), puis
compare entre elles les parties d'un même morceau (même titre).
Le fichier d'origine n'est jamais modifié.
"""

import argparse
import collections
import sys
from pathlib import Path

from recomuse import paths
from recomuse.importer import ScoreImportError, import_score
from recomuse.model.build import build_model
from recomuse.model.score import ScoreModel
from recomuse.model.split import split_parts
from recomuse.recognition.__main__ import parse_page_range
from recomuse.recognition.audiveris import AudiverisError
from recomuse.recognition.pipeline import recognize_score
from recomuse.recognition.tools import ToolNotFoundError
from recomuse.validation.comparison import compare_parts, group_by_title, part_refs
from recomuse.validation.issues import ValidationReport
from recomuse.validation.validator import tesseract_number_reader, validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recomuse.validation")
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--pages", type=parse_page_range, default=None)
    parser.add_argument("--out", type=Path, default=None, help="dossier de travail")
    parser.add_argument("--audiveris", action="store_true",
                        help="lire aussi les pages vectorielles avec Audiveris")
    parser.add_argument("--detail", action="store_true", help="affiche chaque problème")
    parser.add_argument("--compare", action="store_true",
                        help="compare entre elles les parties d'un même morceau")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    if args.compare:
        models = []
        for file in args.files:
            loaded = _load(file, args)
            if loaded is None:
                return 1
            model, recognition, _ = loaded
            models += split_parts(model, recognition.page_headers)
        for title, group in group_by_title(models).items():
            refs = part_refs(group)
            print(f"{title} : {len(refs)} partie(s) "
                  f"{[(r.label, sum(m.length for m in r.part.measures)) for r in refs]}")
            _print_report(compare_parts(refs), detail=True)
        return 0

    if len(args.files) > 1:
        parser.error("un seul fichier sans --compare")
    loaded = _load(args.files[0], args)
    if loaded is None:
        return 1
    model, _, work_dir = loaded
    report = validate(model, read_number=tesseract_number_reader(work_dir / "validation"))

    print(f"{model.title} / {model.instrument} : "
          f"{sum(m.length for p in model.parts for m in p.measures)} mesures, "
          f"{len(model.parts)} partie(s), pages {[(p.number, p.source) for p in model.pages]}")
    _print_report(report, args.detail)
    return 0


def _load(file: Path, args) -> tuple[ScoreModel, object, Path] | None:
    """Importe, reconnaît et construit le modèle d'un fichier ; None en cas d'échec."""
    work_dir = (args.out or paths.imports_dir()) / file.stem
    try:
        score = import_score(file, work_dir)
        if args.pages:
            first, last = args.pages
            score.pages = [p for p in score.pages if first <= p.page_number <= last]
        recognition = recognize_score(score, audiveris_for_vector_pages=args.audiveris)
    except (ScoreImportError, ToolNotFoundError, AudiverisError) as error:
        print(f"ÉCHEC : {file.name} : {error.code}")
        return None
    if args.audiveris:
        recognition.vector = None   # le modèle est construit d'après Audiveris seul
    model = build_model(score, recognition, vector=None if args.audiveris else recognition.vector)
    return model, recognition, work_dir


def _print_report(report: ValidationReport, detail: bool) -> None:
    counts = collections.Counter(i.code for i in report.issues)
    print(f"Problèmes : {len(report.issues)} {dict(counts)}")
    for issue in report.issues:
        if not detail and issue.code in ("measure_duration", "note_position_mismatch",
                                         "note_out_of_range"):
            continue
        details = {k: v for k, v in issue.details.items() if k not in ("measure_id",)}
        fixes = f", {len(issue.fixes)} correction(s) proposée(s)" if issue.fixes else ""
        action = f", action {issue.action}" if issue.action else ""
        print(f"  [{issue.severity}] {issue.code} {issue.part_id} mesures "
              f"{issue.measure_numbers[:6]}{'...' if len(issue.measure_numbers) > 6 else ''} "
              f"confiance {issue.confidence:.2f} {details}{fixes}{action}")


if __name__ == "__main__":
    sys.exit(main())
