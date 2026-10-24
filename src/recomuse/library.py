"""Bibliothèque des partitions : ouvrir un fichier et retrouver les partitions déjà lues.

Ouvrir un fichier enchaîne tout le travail du moteur :
import (pages préparées à 300 dpi) → reconnaissance (lecture vectorielle, Audiveris,
textes) → modèle interne → séparation des parties (un PDF peut les contenir toutes).
Chaque partie devient une partition de la base, avec son modèle. Les parties d'un même
morceau (même titre) sont comparées entre elles pour poser les questions (piece_of).
Un conducteur (tous les instruments sur chaque système) peut être découpé en parties, et
des parties séparées réunies en un conducteur (model/conductor.py).
Une partie déjà lue et corrigée (mêmes pages : learning/memory.py) reprend ses
corrections et ses réponses aux questions ; à défaut, celles d'un pack d'apprentissage
reçu d'un autre membre (learning/packs.py).

C'est long (une ou deux minutes pour une page scannée) : `progress` est appelé à chaque
étape, pour que l'interface puisse dire où on en est.
"""

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

from recomuse import paths
from recomuse.export.mei import model_to_mei
from recomuse.importer import import_score, register_score
from recomuse.learning import memory, packs
from recomuse.learning.corrections import CorrectionService
from recomuse.model import conductor
from recomuse.model.build import build_model
from recomuse.model.score import ScoreModel
from recomuse.model.split import normalized, split_parts
from recomuse.model.store import load_model, save_model
from recomuse.questions.images import page_image
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
    created: set[int] = set()
    for part in parts:
        score_id = register_score(conn, score, title=part.title, part_name=part.instrument)
        created.add(score_id)
        save_model(conn, score_id, part)
        # Partition déjà lue et corrigée ? Ses corrections sont reprises.
        prints = memory.page_fingerprints(part)
        previous = memory.find_previous(conn, prints, exclude=created)
        memory.store(conn, score_id, prints)
        result = summary(score_id, part)
        shared = packs.find_score(conn, prints) if previous is None else None
        if previous is not None:
            replayed = memory.replay(conn, CorrectionService(conn), previous, score_id)
            replayed["read_at"] = conn.execute(
                "SELECT imported_at FROM scores WHERE id = ?", (previous,)).fetchone()[0]
            result = summary(score_id, load_model(conn, score_id)) | {"memory": replayed}
        elif shared is not None:
            # La même partie, corrigée par un autre membre (pack d'apprentissage).
            replayed = memory.replay_work(conn, CorrectionService(conn), shared["corrections"],
                                          shared["answers"], score_id,
                                          f"pack:{shared['pack_id']}")
            replayed |= {"from_pack": shared["pack_id"], "author": shared["author"],
                         "read_at": shared["created_at"]}
            result = summary(score_id, load_model(conn, score_id)) | {"memory": replayed}
        summaries.append(result)
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


def piece_of(conn: sqlite3.Connection, score_id: int) -> list[int]:
    """Partitions du même morceau que `score_id` (elle comprise), dans l'ordre de lecture :
    celles qui ont le même titre, que les parties viennent d'un seul PDF ou de fichiers
    séparés. Sans titre lu, celles qui viennent du même fichier."""
    row = conn.execute("SELECT title, source_path FROM scores WHERE id = ?",
                       (score_id,)).fetchone()
    if row is None:
        return []
    title = normalized(row[0])
    rows = conn.execute(
        "SELECT s.id, s.title, s.source_path FROM scores s "
        "JOIN score_models m ON m.score_id = s.id ORDER BY s.id").fetchall()
    if title:
        return [r[0] for r in rows if normalized(r[1]) == title]
    return [r[0] for r in rows if not normalized(r[1]) and r[2] == row[1]]


def page_view(conn: sqlite3.Connection, score_id: int, page_number: int) -> dict | None:
    """Une page pour la vue côte à côte : son image, sa taille d'origine (les boîtes sont
    en pixels de l'image à 300 dpi) et les mesures qu'elle contient. None si la partition
    ou la page n'existe pas."""
    model = load_model(conn, score_id)
    page = model.page(page_number) if model else None
    if page is None:
        return None
    image = None
    if page.image_path and Path(page.image_path).is_file():
        image = page_image(Path(page.image_path))
    measures = [{"id": m.id, "number": m.number, "length": m.length, "part_id": part.id,
                 "bbox": list(m.bbox)}
                for part in model.parts for m in part.measures
                if m.page == page_number and m.bbox is not None]
    return {"score_id": score_id, "page": page_number, "image": image,
            "width": page.width, "height": page.height, "measures": measures,
            "pages": [p.number for p in model.pages if p.source != "none"]}


def rendering(conn: sqlite3.Connection, score_id: int) -> dict | None:
    """La partition reconnue, en MEI pour Verovio, avec la correspondance entre les
    identifiants du MEI et ceux du modèle, et la page de chaque mesure."""
    model = load_model(conn, score_id)
    if model is None:
        return None
    result = model_to_mei(model)
    result["measure_pages"] = {m.id: m.page for part in model.parts for m in part.measures}
    result["score_id"] = score_id
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
        # Conducteur (lu ou assemblé) : ses instruments ; partition tirée d'autres.
        "instruments": [g[0].name for g in conductor.instrument_groups(model)]
        if conductor.is_conductor(model) else [],
        "derived": model.derived,
    }


# --- Conducteurs --------------------------------------------------------------------------


def extract_parts(conn: sqlite3.Connection, score_id: int) -> list[dict]:
    """Une partition par instrument du conducteur `score_id`, enregistrées comme de
    nouvelles partitions (le conducteur ne change pas). Renvoie leurs résumés."""
    model = load_model(conn, score_id)
    if model is None or not conductor.is_conductor(model):
        return []
    result = []
    for part in conductor.extract_parts(model):
        part.derived_from = [score_id]
        new_id = _register_derived(conn, score_id, part)
        result.append(summary(new_id, part))
    return result


def assemble_conductor(conn: sqlite3.Connection, score_ids: list[int]) -> dict | None:
    """Conducteur fait des partitions `score_ids` (une partie par instrument), enregistré
    comme une nouvelle partition. Renvoie son résumé (None si une partition manque)."""
    models = [(score_id, load_model(conn, score_id)) for score_id in score_ids]
    if len(models) < 2 or any(model is None for _, model in models):
        return None
    result = conductor.assemble(models)
    new_id = _register_derived(conn, score_ids[0], result)
    return summary(new_id, result)


def piece_scores(conn: sqlite3.Connection, score_id: int) -> list[dict]:
    """Partitions du même morceau (même titre), pour choisir celles d'un conducteur."""
    result = []
    for other_id in piece_of(conn, score_id):
        model = load_model(conn, other_id)
        if model is not None:
            result.append(summary(other_id, model))
    return result


def _register_derived(conn: sqlite3.Connection, source_id: int, model: ScoreModel) -> int:
    """Enregistre une partition tirée d'une autre (même fichier d'origine)."""
    row = conn.execute("SELECT source_path, source_kind, page_count FROM scores WHERE id = ?",
                       (source_id,)).fetchone()
    with conn:
        cursor = conn.execute(
            "INSERT INTO scores (title, part_name, source_path, source_kind, page_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (model.title, model.instrument, row[0], row[1], row[2]))
    save_model(conn, cursor.lastrowid, model)
    return cursor.lastrowid


def _folder_name(source: Path) -> str:
    """Nom du dossier de travail d'un fichier : son nom, sans caractères gênants."""
    return re.sub(r"[^\w.-]+", "_", source.stem).strip("_") or "partition"
