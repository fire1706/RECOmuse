"""Enregistrement du modèle interne dans la base locale (table score_models, en JSON)."""

import json
import sqlite3

from recomuse.model.score import ScoreModel


def save_model(conn: sqlite3.Connection, score_id: int, model: ScoreModel,
               commit: bool = True) -> None:
    """Enregistre (ou remplace) le modèle d'une partition.

    commit=False : à l'intérieur d'une transaction déjà ouverte par l'appelant (le service
    de corrections enregistre le journal et le modèle ensemble).
    """
    data = json.dumps(model.to_dict(), ensure_ascii=False)
    sql = """
        INSERT INTO score_models (score_id, model_json) VALUES (?, ?)
        ON CONFLICT(score_id) DO UPDATE SET
            model_json = excluded.model_json,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    """
    if commit:
        with conn:
            conn.execute(sql, (score_id, data))
    else:
        conn.execute(sql, (score_id, data))


def load_model(conn: sqlite3.Connection, score_id: int) -> ScoreModel | None:
    """Relit le modèle d'une partition (None s'il n'a pas encore été construit)."""
    row = conn.execute("SELECT model_json FROM score_models WHERE score_id = ?",
                       (score_id,)).fetchone()
    return ScoreModel.from_dict(json.loads(row[0])) if row else None
