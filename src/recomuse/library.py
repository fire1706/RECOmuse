"""Bibliothèque des partitions : ouvrir un fichier et retrouver les partitions déjà lues.

Ouvrir un fichier enchaîne tout le travail du moteur :
import (pages préparées à 300 dpi) → reconnaissance (lecture vectorielle, Audiveris,
textes) → modèle interne → séparation des parties (un PDF peut les contenir toutes).
Chaque partie devient une partition de la base, avec son modèle.

C'est long (une ou deux minutes pour une page scannée) : `progress` est appelé à chaque
étape, pour que l'interface puisse dire où on en est.
"""

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

from recomuse import paths
from recomuse.importer import import_score, register_score
from recomuse.model.build import build_model
from recomuse.model.score import ScoreModel
from recomuse.model.split import split_parts
from recomuse.model.store import load_model, save_model
from recomuse.recognition.pipeline import recognize_score

# Étapes annoncées à l'interface (traduites par elle).
STAGES = ("import", "recognition", "model", "done")

ProgressCallback = Callable[[str], None]


def open_file(conn: sqlite3.Connection, source: Path | str,
              progress: ProgressCallback | None = None,
              work_root: Path | None = None) -> list[dict]:
    """Lit un fichier (PDF ou image) et enregistre une partition par partie trouvée.
    Renvoie le résumé de chacune. Le fichier d'origine n'est jamais modifié.

    Lève les erreurs du moteur (import, outil manquant, Audiveris) : leur `code` est
    traduit par l'interface."""
    report = progress or (lambda stage: None)
    source = Path(source)
    work_dir = (work_root or paths.imports_dir()) / _folder_name(source)

    report("import")
    score = import_score(source, work_dir)
    report("recognition")
    recognition = recognize_score(score)
    report("model")
    model = build_model(score, recognition)
    parts = split_parts(model, recognition.page_headers)

    summaries = []
    for part in parts:
        score_id = register_score(conn, score, title=part.title, part_name=part.instrument)
        save_model(conn, score_id, part)
        summaries.append(summary(score_id, part))
    report("done")
    return summaries


def list_scores(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Partitions déjà lues, de la plus récente à la plus ancienne."""
    rows = conn.execute(
        "SELECT s.id FROM scores s JOIN score_models m ON m.score_id = s.id "
        "ORDER BY s.id DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for (score_id,) in rows:
        model = load_model(conn, score_id)
        if model is not None:
            result.append(summary(score_id, model))
    return result


def summary(score_id: int, model: ScoreModel) -> dict:
    """Ce que l'interface affiche d'une partition."""
    first = model.parts[0] if model.parts else None
    return {
        "score_id": score_id,
        "title": model.title,
        "instrument": model.instrument,
        "source_name": Path(model.source_path).name if model.source_path else None,
        "pages": [p.number for p in model.pages],
        "measure_count": sum(m.length for m in first.measures) if first else 0,
    }


def _folder_name(source: Path) -> str:
    """Nom du dossier de travail d'un fichier : son nom, sans caractères gênants."""
    return re.sub(r"[^\w.-]+", "_", source.stem).strip("_") or "partition"
