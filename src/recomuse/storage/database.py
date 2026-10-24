"""Ouverture de la base SQLite locale et création / mise à jour de son schéma.

La version du schéma est rangée dans la base elle-même (PRAGMA user_version).
- Base neuve (version 0) : on exécute schema.sql, puis on passe en version 1.
- Plus tard, chaque évolution du schéma sera une migration numérotée ajoutée
  à la liste MIGRATIONS ; elle ne sera exécutée qu'une fois par base.
"""

import sqlite3
from importlib import resources
from pathlib import Path

from recomuse import paths

# Version du schéma que ce code sait utiliser.
SCHEMA_VERSION = 4

# Migrations à appliquer après schema.sql, dans l'ordre.
# Chaque élément est (version atteinte, script SQL).
MIGRATIONS: list[tuple[int, str]] = [
    # Version 2 (tâche 5) : modèle interne de chaque partition, en JSON (model/score.py).
    # Rangé dans la base, à côté du journal : une correction met à jour les deux dans une
    # seule transaction (tout ou rien).
    (2, """
        CREATE TABLE score_models (
            score_id    INTEGER PRIMARY KEY REFERENCES scores(id),
            model_json  TEXT    NOT NULL CHECK (json_valid(model_json)),
            updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        );
    """),
    # Version 3 (tâche 8) : réponses aux questions guidées. Une question à laquelle on a
    # répondu n'est plus posée, même si la réponse était « c'est juste, ne rien changer »
    # (cette réponse-là ne crée aucune correction). Une réponse annulée reste dans la
    # table, marquée « undone », pour garder l'histoire des réponses.
    (3, """
        CREATE TABLE question_answers (
            id              INTEGER PRIMARY KEY,
            score_id        INTEGER NOT NULL REFERENCES scores(id),
            question_key    TEXT    NOT NULL,   -- identifiant stable de la question
            code            TEXT    NOT NULL,   -- type de doute (ex. multirest_missed)
            choice_id       TEXT    NOT NULL,   -- choix de l'utilisateur
            value           TEXT    CHECK (value IS NULL OR json_valid(value)),
            correction_ids  TEXT    NOT NULL CHECK (json_valid(correction_ids)),
            answered_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            undone          INTEGER NOT NULL DEFAULT 0 CHECK (undone IN (0, 1))
        );
        CREATE INDEX idx_question_answers_score ON question_answers(score_id);
    """),
    # Version 4 (tâche 9b) : place d'un symbole ajouté ou supprimé dans sa mesure
    # (identifiant de la mesure, liste « attributes » ou « events », rang), en JSON.
    # Annuler la suppression d'une note la remet exactement où elle était.
    (4, """
        ALTER TABLE corrections ADD COLUMN location TEXT
            CHECK (location IS NULL OR json_valid(location));
    """),
]


class DatabaseTooNewError(RuntimeError):
    """La base a été créée par une version plus récente de RECOmuse."""


def _read_schema() -> str:
    """Lit le fichier schema.sql livré avec le paquet."""
    return resources.files("recomuse.storage").joinpath("schema.sql").read_text(encoding="utf-8")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Ouvre la base (la crée si besoin) et s'assure que son schéma est à jour.

    db_path : chemin du fichier ; par défaut, la base de l'utilisateur.
              La valeur spéciale ":memory:" crée une base en mémoire (pour les tests).
    """
    if db_path is None:
        db_path = paths.database_path()

    # check_same_thread=False : pywebview appelle l'API Python depuis un autre fil
    # d'exécution que celui qui a ouvert la base.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    # Accès aux colonnes par leur nom : row["new_value"].
    conn.row_factory = sqlite3.Row
    # SQLite n'applique les clés étrangères que si on le lui demande.
    conn.execute("PRAGMA foreign_keys = ON")

    migrate(conn)
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """Version du schéma actuellement enregistrée dans la base."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    """Amène le schéma de la base à SCHEMA_VERSION."""
    version = schema_version(conn)

    if version > SCHEMA_VERSION:
        raise DatabaseTooNewError(
            f"La base est en version {version}, ce logiciel ne connaît que la version "
            f"{SCHEMA_VERSION}. Mettez RECOmuse à jour."
        )

    if version == 0:
        # executescript valide lui-même la transaction en cours, puis exécute tout le script.
        conn.executescript("BEGIN;\n" + _read_schema() + "\nPRAGMA user_version = 1;\nCOMMIT;")
        version = 1

    for target, script in MIGRATIONS:
        if version < target:
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {target};\nCOMMIT;")
            version = target
