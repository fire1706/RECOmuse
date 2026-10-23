"""Journal des corrections : le service UNIQUE par lequel passe toute correction.

Que la correction vienne d'une réponse à une question, d'une édition manuelle,
d'une règle apprise ou du validateur, elle est enregistrée ici, avec tout ce qu'il
faut pour en apprendre plus tard : où se trouve le symbole, son extrait d'image,
l'ancienne et la nouvelle valeur, la confiance du moteur et ses alternatives.

Le journal est en ajout seul. Annuler une correction = enregistrer une nouvelle
correction (source « revert ») qui remet l'ancienne valeur et référence l'originale.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

# Origines possibles d'une correction (mêmes valeurs que la contrainte CHECK du schéma).
CorrectionSource = Literal["question", "manual", "rule", "validator", "revert"]


@dataclass(frozen=True)
class BoundingBox:
    """Boîte d'un symbole sur la page, en pixels de l'image à 300 dpi."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Correction:
    """Une correction, telle qu'elle est enregistrée dans le journal.

    Les valeurs (old_value, new_value, alternatives) peuvent être de simples textes
    ou des dictionnaires, par ex. {"step": "C", "octave": 6} : elles sont stockées en JSON.
    """

    symbol_kind: str
    new_value: Any
    source: CorrectionSource
    old_value: Any = None
    score_id: int | None = None
    page_number: int | None = None
    measure_number: int | None = None
    staff_number: int | None = None
    symbol_id: str | None = None
    bbox: BoundingBox | None = None
    snippet_path: str | None = None
    confidence: float | None = None
    alternatives: list[Any] = field(default_factory=list)
    group_id: str | None = None
    reason: str | None = None
    reverts_id: int | None = None
    # Rempli par le journal à la lecture ; à laisser vide lors d'un enregistrement.
    id: int | None = None
    created_at: str | None = None


def _to_json(value: Any) -> str | None:
    """Convertit une valeur Python en texte JSON (None reste None)."""
    if value is None:
        return None
    # ensure_ascii=False : garde les accents lisibles dans la base.
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(text: str | None) -> Any:
    return None if text is None else json.loads(text)


class CorrectionJournal:
    """Accès au journal des corrections stocké dans la base SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, correction: Correction) -> int:
        """Enregistre une correction et renvoie son numéro dans le journal."""
        if correction.id is not None:
            raise ValueError("Une correction déjà enregistrée ne peut pas l'être une seconde fois.")
        if correction.source == "revert" and correction.reverts_id is None:
            raise ValueError("Une annulation doit indiquer la correction qu'elle annule.")
        if correction.source != "revert" and correction.reverts_id is not None:
            raise ValueError("Seule une annulation (source « revert ») peut référencer une correction.")

        bbox = correction.bbox
        with self._conn:  # transaction : tout ou rien
            cursor = self._conn.execute(
                """
                INSERT INTO corrections (
                    score_id, page_number, measure_number, staff_number,
                    symbol_id, symbol_kind,
                    bbox_x, bbox_y, bbox_width, bbox_height, snippet_path,
                    old_value, new_value, confidence, alternatives,
                    source, group_id, reason, reverts_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correction.score_id,
                    correction.page_number,
                    correction.measure_number,
                    correction.staff_number,
                    correction.symbol_id,
                    correction.symbol_kind,
                    bbox.x if bbox else None,
                    bbox.y if bbox else None,
                    bbox.width if bbox else None,
                    bbox.height if bbox else None,
                    correction.snippet_path,
                    _to_json(correction.old_value),
                    # new_value est obligatoire : « aucune valeur » (symbole supprimé)
                    # est stockée comme le JSON null, pas comme une case vide.
                    json.dumps(correction.new_value, ensure_ascii=False, sort_keys=True),
                    correction.confidence,
                    _to_json(correction.alternatives) if correction.alternatives else None,
                    correction.source,
                    correction.group_id,
                    correction.reason,
                    correction.reverts_id,
                ),
            )
        return cursor.lastrowid

    def revert(self, correction_id: int) -> int:
        """Annule une correction en enregistrant la correction inverse.

        Renvoie le numéro de la nouvelle ligne du journal.
        """
        original = self.get(correction_id)
        if original is None:
            raise KeyError(f"Aucune correction n° {correction_id} dans le journal.")

        return self.record(
            Correction(
                symbol_kind=original.symbol_kind,
                # On échange l'ancienne et la nouvelle valeur.
                old_value=original.new_value,
                new_value=original.old_value,
                source="revert",
                reverts_id=original.id,
                score_id=original.score_id,
                page_number=original.page_number,
                measure_number=original.measure_number,
                staff_number=original.staff_number,
                symbol_id=original.symbol_id,
                bbox=original.bbox,
                snippet_path=original.snippet_path,
                group_id=original.group_id,
            )
        )

    def get(self, correction_id: int) -> Correction | None:
        """Relit une correction par son numéro (None si elle n'existe pas)."""
        row = self._conn.execute(
            "SELECT * FROM corrections WHERE id = ?", (correction_id,)
        ).fetchone()
        return _row_to_correction(row) if row else None

    def list_for_score(self, score_id: int) -> list[Correction]:
        """Toutes les corrections d'une partition, dans l'ordre où elles ont été faites."""
        rows = self._conn.execute(
            "SELECT * FROM corrections WHERE score_id = ? ORDER BY id", (score_id,)
        ).fetchall()
        return [_row_to_correction(row) for row in rows]

    def count(self) -> int:
        """Nombre total de lignes dans le journal."""
        return self._conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]


def _row_to_correction(row: sqlite3.Row) -> Correction:
    """Transforme une ligne de la table « corrections » en objet Correction."""
    bbox = None
    if row["bbox_x"] is not None:
        bbox = BoundingBox(row["bbox_x"], row["bbox_y"], row["bbox_width"], row["bbox_height"])

    return Correction(
        id=row["id"],
        created_at=row["created_at"],
        score_id=row["score_id"],
        page_number=row["page_number"],
        measure_number=row["measure_number"],
        staff_number=row["staff_number"],
        symbol_id=row["symbol_id"],
        symbol_kind=row["symbol_kind"],
        bbox=bbox,
        snippet_path=row["snippet_path"],
        old_value=_from_json(row["old_value"]),
        new_value=_from_json(row["new_value"]),
        confidence=row["confidence"],
        alternatives=_from_json(row["alternatives"]) or [],
        source=row["source"],
        group_id=row["group_id"],
        reason=row["reason"],
        reverts_id=row["reverts_id"],
    )
