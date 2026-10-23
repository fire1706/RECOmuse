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
SCHEMA_VERSION = 1

# Migrations à appliquer après schema.sql, dans l'ordre.
# Chaque élément est (version atteinte, script SQL). Vide pour l'instant.
MIGRATIONS: list[tuple[int, str]] = []


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
