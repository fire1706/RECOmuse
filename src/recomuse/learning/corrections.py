"""Service UNIQUE de corrections : toute modification d'un symbole passe par ici.

Que la correction vienne d'une réponse à une question, d'une édition manuelle, d'une
règle apprise ou du validateur, ce service :
1. découpe l'extrait d'image du symbole (pour l'apprentissage) ;
2. enregistre la correction dans le journal (ancienne et nouvelle valeur, position,
   confiance, alternatives...) ;
3. modifie le symbole dans le modèle interne de la partition ;
les étapes 2 et 3 dans une seule transaction : si l'une échoue, rien n'est enregistré.

Une correction peut aussi AJOUTER un symbole que la lecture a manqué (une pause multiple,
un chiffrage) : le journal l'enregistre sans ancienne valeur, et l'annuler le retire.

L'historique des valeurs d'un symbole se lit dans le journal (history).
"""

import sqlite3
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recomuse import paths
from recomuse.learning.journal import BoundingBox, Correction, CorrectionJournal, CorrectionSource
from recomuse.model.score import VALUE_FIELDS, Measure, ScoreModel, Symbol, SymbolKind
from recomuse.model.snippets import crop_snippet
from recomuse.model.store import load_model, save_model

# Source du symbole dans le modèle après une correction, selon l'origine de la correction.
SYMBOL_SOURCE = {"question": "user", "manual": "user", "rule": "rule", "validator": "validator"}

# Ordre des réglages en tête de mesure : un symbole ajouté y prend sa place.
ATTRIBUTE_ORDER = ("clef", "key", "time", "multirest")


@dataclass
class NewSymbol:
    """Symbole à ajouter dans une mesure (clé, armure, chiffrage ou pause multiple)."""

    measure_id: str
    kind: SymbolKind
    value: dict[str, Any]


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
                    source: CorrectionSource, reason: str | None = None,
                    additions: list[NewSymbol] | None = None) -> list[int]:
        """Corrige plusieurs symboles d'un coup : une seule réponse de l'utilisateur peut
        corriger plusieurs mesures (même cause). `additions` : symboles à ajouter.
        Toutes les corrections partagent un même numéro de groupe, et sont enregistrées
        ensemble ou pas du tout. Renvoie leurs numéros dans le journal."""
        if source == "revert":
            raise ValueError("Pour annuler une correction, utiliser revert().")
        additions = additions or []
        model = self._model(score_id)
        group_id = uuid.uuid4().hex if len(changes) + len(additions) > 1 else None

        # Tout est vérifié AVANT d'écrire quoi que ce soit.
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
        added = []
        for addition in additions:
            measure, symbol = self._new_symbol(model, addition, source, added)
            added.append((measure, symbol, self._snippet(score_id, model, symbol)))

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
            for measure, symbol, snippet in added:
                _insert_attribute(measure, symbol)
                ids.append(self._journal.record(
                    _correction(score_id, measure, symbol, None, deepcopy(symbol.value),
                                source, reason, group_id, snippet),
                    commit=False))
            # Une pause multiple change la numérotation des mesures qui la suivent, un
            # chiffrage la durée attendue des mesures qui le suivent.
            model.refresh()
            save_model(self._conn, score_id, model, commit=False)
        return ids

    def revert(self, correction_id: int) -> int:
        """Annule une correction : le symbole reprend sa valeur d'avant (un symbole ajouté
        est retiré). Renvoie le numéro de l'annulation dans le journal (l'original y reste,
        le journal est en ajout seul)."""
        return self.revert_all([correction_id])[0]

    def revert_all(self, correction_ids: list[int]) -> list[int]:
        """Annule plusieurs corrections d'une même partition (toute une réponse), de la
        dernière à la première, ensemble ou pas du tout. Renvoie les numéros des
        annulations, dans l'ordre des corrections annulées."""
        originals = []
        for correction_id in correction_ids:
            original = self._journal.get(correction_id)
            if original is None:
                raise CorrectionError(f"Aucune correction n° {correction_id}.")
            if original.score_id is None or original.symbol_id is None:
                raise CorrectionError("Correction sans partition ni symbole : rien à annuler.")
            originals.append(original)
        if not originals:
            return []
        score_id = originals[0].score_id
        if any(o.score_id != score_id for o in originals):
            raise CorrectionError("Corrections de plusieurs partitions : à annuler séparément.")
        model = self._model(score_id)

        ids = []
        with self._conn:
            for original in reversed(originals):
                try:
                    _, measure, symbol = model.find(original.symbol_id)
                except KeyError:
                    raise CorrectionError(f"Symbole introuvable : {original.symbol_id}") from None
                ids.append(self._journal.revert(original.id, commit=False))
                if original.old_value is None:
                    measure.attributes.remove(symbol)   # c'était un ajout : on le retire
                else:
                    symbol.value = original.old_value
                    # Le symbole redevient ce qu'il était : même confiance, même origine
                    # (le validateur ne vérifie que ce qu'a lu Audiveris, par exemple).
                    if original.confidence is not None:
                        symbol.confidence = original.confidence
                    symbol.source = self._source_before(model, original)
            model.refresh()
            save_model(self._conn, score_id, model, commit=False)
        return ids[::-1]

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

    def _source_before(self, model: ScoreModel, original: Correction) -> str:
        """Origine du symbole juste avant la correction `original` : celle de la correction
        précédente encore en vigueur, sinon celle de la lecture de sa page."""
        history = self.history(original.score_id, original.symbol_id)
        reverted = {c.reverts_id for c in history if c.source == "revert"}
        earlier = [c for c in history if c.source != "revert" and c.id not in reverted
                   and c.id < original.id]
        if earlier:
            return SYMBOL_SOURCE[earlier[-1].source]
        _, _, symbol = model.find(original.symbol_id)
        page = model.page(symbol.page) if symbol.page is not None else None
        if page is not None and page.source in ("vector", "audiveris"):
            return page.source
        return symbol.source

    def _new_symbol(self, model: ScoreModel, addition: NewSymbol, source: CorrectionSource,
                    pending: list) -> tuple[Measure, Symbol]:
        """Prépare un symbole à ajouter, sans encore toucher au modèle. `pending` : les
        ajouts déjà préparés pour la même réponse."""
        try:
            _, measure = model.find_measure(addition.measure_id)
        except KeyError:
            raise CorrectionError(f"Mesure introuvable : {addition.measure_id}") from None
        if addition.kind not in ATTRIBUTE_ORDER:
            raise CorrectionError(f"Ajout impossible pour ce type de symbole : {addition.kind}")
        if any(s.kind == addition.kind for s in measure.attributes) or any(
                m is measure and s.kind == addition.kind for m, s, _ in pending):
            raise CorrectionError(f"La mesure {measure.id} a déjà un symbole {addition.kind}.")
        unknown = set(addition.value) - set(VALUE_FIELDS[addition.kind])
        if unknown:
            raise CorrectionError(f"Champs inconnus pour {addition.kind} : {sorted(unknown)}")
        # Identifiant : celui de la mesure, le type, « + » (ajouté) et un numéro libre.
        taken = {s.id for s in model.symbols()} | {s.id for _, s, _ in pending}
        number = 0
        while f"{measure.id}.{addition.kind}+{number}" in taken:
            number += 1
        # Position : le début de la mesure, là où s'écrit un chiffrage ou une pause.
        bbox = None
        if measure.bbox is not None:
            x, y, w, h = measure.bbox
            bbox = (x, y, min(w, h), h)
        symbol = Symbol(id=f"{measure.id}.{addition.kind}+{number}", kind=addition.kind,
                        value=dict(addition.value), page=measure.page, bbox=bbox,
                        source=SYMBOL_SOURCE[source])
        return measure, symbol

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


def _insert_attribute(measure: Measure, symbol: Symbol) -> None:
    """Range le symbole ajouté à sa place parmi les réglages de la mesure."""
    rank = ATTRIBUTE_ORDER.index(symbol.kind)
    position = next((k for k, s in enumerate(measure.attributes)
                     if s.kind in ATTRIBUTE_ORDER and ATTRIBUTE_ORDER.index(s.kind) > rank),
                    len(measure.attributes))
    measure.attributes.insert(position, symbol)


def _correction(score_id: int, measure: Measure, symbol: Symbol, old: dict | None, new: dict,
                source: CorrectionSource, reason: str | None, group_id: str | None,
                snippet: str | None) -> Correction:
    bbox = BoundingBox(*symbol.bbox) if symbol.bbox else None
    return Correction(
        score_id=score_id, page_number=symbol.page, measure_number=measure.number,
        symbol_id=symbol.id, symbol_kind=symbol.kind, bbox=bbox, snippet_path=snippet,
        old_value=old, new_value=new, confidence=symbol.confidence,
        alternatives=symbol.alternatives, source=source, group_id=group_id, reason=reason,
    )
