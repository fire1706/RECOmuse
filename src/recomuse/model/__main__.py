"""Essai du modèle interne en ligne de commande (outil de développement).

    python -m recomuse.model partition.pdf [--pages 1-2] [--out DOSSIER] [--db base.sqlite3]
                                           [--snippets 5]

Importe, reconnaît, construit le modèle, l'enregistre dans la base (par défaut la base
locale de RECOmuse) et en affiche le résumé. --snippets N découpe les extraits d'image
des N symboles les moins sûrs, pour vérifier les positions. Le fichier d'origine n'est
jamais modifié.
"""

import argparse
import json
import sys
from pathlib import Path

from recomuse import paths
from recomuse.importer import ScoreImportError, import_score, register_score
from recomuse.model.build import build_model
from recomuse.model.snippets import crop_snippet
from recomuse.model.store import save_model
from recomuse.recognition.__main__ import parse_page_range
from recomuse.recognition.audiveris import AudiverisError
from recomuse.recognition.pipeline import recognize_score
from recomuse.recognition.tools import ToolNotFoundError
from recomuse.storage import database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recomuse.model")
    parser.add_argument("file", type=Path)
    parser.add_argument("--pages", type=parse_page_range, default=None)
    parser.add_argument("--out", type=Path, default=None, help="dossier de travail")
    parser.add_argument("--db", type=Path, default=None,
                        help="base SQLite (par défaut : la base locale)")
    parser.add_argument("--snippets", type=int, default=0,
                        help="extraits des N symboles les moins sûrs")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    work_dir = (args.out or paths.imports_dir()) / args.file.stem
    try:
        score = import_score(args.file, work_dir)
    except ScoreImportError as error:
        print(f"ÉCHEC de l'import : {error.code} {error.detail}")
        return 1
    if args.pages:
        first, last = args.pages
        score.pages = [p for p in score.pages if first <= p.page_number <= last]
    try:
        recognition = recognize_score(score)
    except (ToolNotFoundError, AudiverisError) as error:
        print(f"ÉCHEC de la reconnaissance : {error.code}")
        return 1

    model = build_model(score, recognition)
    conn = database.connect(args.db)
    score_id = register_score(conn, score, title=model.title, part_name=model.instrument)
    save_model(conn, score_id, model)
    (work_dir / "model.json").write_text(json.dumps(model.to_dict(), ensure_ascii=False, indent=1),
                                         encoding="utf-8")

    print(f"Partition n° {score_id} : {model.title} / {model.instrument}")
    print(f"Pages : {[(p.number, p.source) for p in model.pages]}")
    symbols = list(model.symbols())
    unsure = sorted((s for s in symbols if s.confidence < 0.7), key=lambda s: s.confidence)
    for part in model.parts:
        wrong = [m.number for m in part.measures if m.expected_duration is not None
                 and m.duration() is not None and m.length == 1
                 and not any(s.value.get("full_measure") for s in m.events)
                 and str(m.duration()) != m.expected_duration]
        total = sum(m.length for m in part.measures)
        print(f"Partie {part.id} ({part.name}) : {total} mesures, durées fausses {wrong[:15]}"
              + (" ..." if len(wrong) > 15 else ""))
    print(f"Symboles : {len(symbols)}, dont {len(unsure)} peu sûrs (confiance < 0,7), "
          f"{sum(1 for s in symbols if s.bbox is None)} sans position")
    for symbol in unsure[:args.snippets]:
        page = model.page(symbol.page) if symbol.page else None
        if page and page.image_path and symbol.bbox:
            out = work_dir / "extraits" / f"{symbol.id}.png"
            crop_snippet(Path(page.image_path), symbol.bbox, out)
            print(f"  {symbol.id} {symbol.kind} {symbol.value.get('step', '')}"
                  f"{symbol.value.get('octave', '')} confiance {symbol.confidence:.2f} -> {out}")
    print(f"-> {work_dir / 'model.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
