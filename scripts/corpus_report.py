"""Passe tout le corpus de partitions dans la chaîne complète de RECOmuse et fait un rapport.

Pour chaque fichier : import, reconnaissance (lecture vectorielle ou Audiveris), modèle,
séparation des parties, questions et passages à vérifier, export MusicXML ; avec le temps
passé et ce qui a échoué. Le rapport (Markdown) va dans build/corpus-report.md, qui n'est
pas versionné (il cite les titres des partitions du corpus).

Le corpus est en LECTURE SEULE ; tout le travail se fait dans une base et un dossier
temporaires.

Usage :  .venv\\Scripts\\python scripts\\corpus_report.py [--pages N] [--only PRÉFIXE]
--pages N : au plus N pages par fichier (Audiveris met une minute environ par page
scannée) ; 0 = toutes.
"""

import argparse
import sys
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

from recomuse.export import files as exports
from recomuse.importer import import_score, register_score
from recomuse.model.build import build_model
from recomuse.model.split import split_parts
from recomuse.model.store import save_model
from recomuse.questions.session import QuestionSession
from recomuse.recognition import recognize_score
from recomuse.storage import database

ROOT = Path(__file__).resolve().parents[1]


def corpus_dir() -> Path:
    for candidate in (ROOT / "tests" / "corpus", ROOT / "test" / "corpus"):
        if candidate.is_dir():
            return candidate
    raise SystemExit("Aucun corpus : tests/corpus ou test/corpus.")


def read(pdf: Path, work: Path, conn, pages: int) -> dict:
    """Toute la chaîne pour un fichier ; renvoie une ligne du rapport."""
    row: dict = {"file": pdf.name}
    start = time.perf_counter()
    # Nom coupé à 40 caractères, sans espace ni point final : Windows les retire des noms
    # de dossier, et le chemin ne correspondrait plus.
    score = import_score(pdf, work / "imports" / pdf.stem[:40].rstrip(" ."))
    if pages:
        score.pages = score.pages[:pages]
    row["kinds"] = dict(Counter(p.kind for p in score.pages))
    recognition = recognize_score(score)
    model = build_model(score, recognition)
    parts = split_parts(model, recognition.page_headers)
    row["read_s"] = round(time.perf_counter() - start)
    row["sources"] = dict(Counter(p.source for p in model.pages))
    row["warnings"] = sorted(set(recognition.warnings))

    session = QuestionSession(conn, work_dir=work / "validation")
    questions, checks, measures = Counter(), 0, []
    for part in parts:
        score_id = register_score(conn, score, title=part.title, part_name=part.instrument)
        save_model(conn, score_id, part)
        state = session.state(score_id)
        questions.update(q["code"] for q in state["questions"])
        checks += state["unasked"]
        measures.append(sum(m.length for m in part.parts[0].measures) if part.parts else 0)
        exports.export_score(conn, score_id, "musicxml", work / "exports" / f"{score_id}")
    row |= {"title": model.title, "parts": len(parts), "staves": len(model.parts),
            "measures": measures, "questions": dict(questions), "checks": checks,
            "total_s": round(time.perf_counter() - start)}
    return row


def markdown(rows: list[dict], pages: int) -> str:
    lines = ["# Rapport du corpus RECOmuse", "",
             f"Pages lues par fichier : {pages or 'toutes'}.", "",
             ("| Fichier | Pages (type → lu par) | Parties | Mesures | Questions | "
             "À vérifier | Temps | Remarques |"),
             "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        if "error" in row:
            lines.append(f"| {row['file']} | | | | | | | **échec** : {row['error']} |")
            continue
        questions = sum(row["questions"].values())
        detail = ", ".join(f"{code} {n}" for code, n in sorted(row["questions"].items()))
        measures = row["measures"]
        shown = (f"{min(measures)}–{max(measures)}" if len(set(measures)) > 1
                 else str(measures[0]) if measures else "0")
        lines.append(
            f"| {row['file']} | {row['kinds']} → {row['sources']} | {row['parts']} "
            f"({row['staves']} portées) | {shown} | {questions} ({detail}) | {row['checks']} | "
            f"{row['total_s']} s | {', '.join(row['warnings'])} |")
    ok = [r for r in rows if "error" not in r]
    lines += ["", (f"{len(ok)} fichiers lus sur {len(rows)} ; "
              f"{sum(r['parts'] for r in ok)} parties ; "
              f"{sum(sum(r['questions'].values()) for r in ok)} questions ; "
              f"{sum(r['total_s'] for r in ok)} s au total.")]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")
    pdfs = sorted(p for p in corpus_dir().glob("*.pdf") if p.name.startswith(args.only))
    rows = []
    with tempfile.TemporaryDirectory(prefix="recomuse-corpus-") as folder:
        work = Path(folder)
        conn = database.connect(work / "corpus.sqlite3")
        for pdf in pdfs:
            print(f"… {pdf.name}", flush=True)
            try:
                rows.append(read(pdf, work, conn, args.pages))
            except Exception as error:  # noqa: BLE001 (un échec ne doit pas arrêter le reste)
                traceback.print_exc()
                rows.append({"file": pdf.name, "error": f"{type(error).__name__}: {error}"})
            print("   ", rows[-1], flush=True)
        conn.close()
    report = ROOT / "build" / "corpus-report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(markdown(rows, args.pages), encoding="utf-8")
    print(f"Rapport : {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
