"""Service UNIQUE de corrections : toute modification d'un symbole passe par ici.

Que la correction vienne d'une réponse à une question, d'une édition manuelle, d'une
règle apprise ou du validateur, ce service :
1. découpe l'extrait d'image du symbole (pour l'apprentissage) ;
2. enregistre la correction dans le journal (ancienne et nouvelle valeur, position,
   confiance, alternatives...) ;
3. modifie le symbole dans le modèle interne de la partition ;
les étapes 2 et 3 dans une seule transaction : si l'une échoue, rien n'est enregistré.

L'historique des valeurs d'un symbole se lit dans le journal (history).
"""

import sqlite3
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from recomuse import paths
from recomuse.learning.journal import BoundingBox, Correction, CorrectionJournal, CorrectionSource
from recomuse.model.score import VALUE_FIELDS, Measure, ScoreModel, Symbol
from recomuse.model.snippets import crop_snippet
from recomuse.model.store import load_model, save_model

# Source du symbole dans le modèle après une correction, selon l'origine de la correction.
SYMBOL_SOURCE = {"question": "user", "manual": "user", "rule": "rule", "validator": "validator"}


class CorrectionError(RuntimeError):
    """La correction ne peut pas être appliquée (partition ou symbole introuvable...)."""


class CorrectionService:
    """Applique et annule les corrections d'une partition, en tenant le journal."""

    def __init__(self, conn: sqlite3.Connection, snippets_dir: Path | None = None) -> None:
        self._conn = conn
        self._journal = CorrectionJournal(conn)
        self._snippets_dir = snippets_dir

    # --- Corrections ---------------------------------------------------------------------------

    def apply(self, score_id: int, symbol_id: str, new_value: dict[str, Any],
              source: CorrectionSource, reason: str | None = None) -> int:
        """Corrige un symbole. `new_value` peut ne contenir que les champs qui changent
        (ex. {"octave": 6}). Renvoie le numéro de la correction dans le journal."""
        return self.apply_group(score_id, [(symbol_id, new_value)], source, reason)[0]

    def apply_group(self, score_id: int, changes: list[tuple[str, dict[str, Any]]],
                    source: CorrectionSource, reason: str | None = None) -> list[int]:
        """Corrige plusieurs symboles d'un coup : une seule réponse de l'utilisateur peut
        corriger plusieurs mesures (même cause). Toutes les corrections partagent un même
        numéro de groupe, et sont enregistrées ensemble ou pas du tout."""
        if source == "revert":
            raise ValueError("Pour annuler une correction, utiliser revert().")
        model = self._model(score_id)
        group_id = uuid.uuid4().hex if len(changes) > 1 else None

        prepared = []
        for symbol_id, new_value in changes:
            try:
                _, measure, symbol = model.find(symbol_id)
            except KeyError:
                raise CorrectionError(f"Symbole introuvable : {symbol_id}") from None
            unknown = set(new_value) - set(symbol.value) - set(VALUE_FIELDS[symbol.kind])
            if unknown:
                raise CorrectionError(f"Champs inconnus pour {symbol.kind} : {sorted(unknown)}")
            merged = {**symbol.value, **new_value}
            prepared.append((measure, symbol, merged, self._snippet(score_id, model, symbol)))

        ids = []
        with self._conn:  # journal et modèle : tout ou rien
            for measure, symbol, merged, snippet in prepared:
                ids.append(self._journal.record(
                    _correction(score_id, measure, symbol, deepcopy(symbol.value), merged,
                                source, reason, group_id, snippet),
                    commit=False))
                symbol.value = merged
                symbol.source = SYMBOL_SOURCE[source]
                symbol.confidence = 1.0
            save_model(self._conn, score_id, model, commit=False)
        return ids

    def revert(self, correction_id: int) -> int:
        """Annule une correction : le symbole reprend sa valeur d'avant. Renvoie le numéro
        de l'annulation dans le journal (l'original y reste, le journal est en ajout seul)."""
        original = self._journal.get(correction_id)
        if original is None:
            raise CorrectionError(f"Aucune correction n° {correction_id}.")
        if original.score_id is None or original.symbol_id is None:
            raise CorrectionError("Correction sans partition ni symbole : rien à annuler.")
        model = self._model(original.score_id)
        try:
            _, _, symbol = model.find(original.symbol_id)
        except KeyError:
            raise CorrectionError(f"Symbole introuvable : {original.symbol_id}") from None
        if original.old_value is None:
            raise CorrectionError("Correction sans valeur d'origine : impossible à annuler.")

        with self._conn:
            revert_id = self._journal.revert(correction_id, commit=False)
            symbol.value = original.old_value
            save_model(self._conn, original.score_id, model, commit=False)
        return revert_id

    # --- Lecture -------------------------------------------------------------------------------

    def history(self, score_id: int, symbol_id: str) -> list[Correction]:
        """Toutes les corrections d'un symbole, de la plus ancienne à la plus récente."""
        return [c for c in self._journal.list_for_score(score_id) if c.symbol_id == symbol_id]

    # --- Interne -------------------------------------------------------------------------------

    def _model(self, score_id: int) -> ScoreModel:
        model = load_model(self._conn, score_id)
        if model is None:
            raise CorrectionError(f"Aucun modèle pour la partition n° {score_id}.")
        return model

    def _snippet(self, score_id: int, model: ScoreModel, symbol: Symbol) -> str | None:
        """Découpe l'extrait d'image du symbole ; renvoie son chemin relatif au dossier
        des extraits, ou None si la page ou la position manque."""
        page = model.page(symbol.page) if symbol.page is not None else None
        if page is None or page.image_path is None or symbol.bbox is None:
            return None
        image = Path(page.image_path)
        if not image.is_file():
            return None
        base = self._snippets_dir or paths.snippets_dir()
        relative = Path(f"score-{score_id}") / f"{symbol.id}.png"
        try:
            crop_snippet(image, symbol.bbox, base / relative)
        except (OSError, ValueError):
            return None   # un extrait manquant ne doit pas empêcher la correction
        return relative.as_posix()


def _correction(score_id: int, measure: Measure, symbol: Symbol, old: dict, new: dict,
                source: CorrectionSource, reason: str | None, group_id: str | None,
                snippet: str | None) -> Correction:
    bbox = BoundingBox(*symbol.bbox) if symbol.bbox else None
    return Correction(
        score_id=score_id, page_number=symbol.page, measure_number=measure.number,
        symbol_id=symbol.id, symbol_kind=symbol.kind, bbox=bbox, snippet_path=snippet,
        old_value=old, new_value=new, confidence=symbol.confidence,
        alternatives=symbol.alternatives, source=source, group_id=group_id, reason=reason,
    )
