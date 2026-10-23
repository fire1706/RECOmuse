"""Outils partagés par les tests Python (« fixtures » pytest)."""

import pytest

from recomuse.storage import database


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Chaque test utilise un dossier de données temporaire :
    les tests ne touchent jamais à la vraie base de l'utilisateur."""
    data_dir = tmp_path / "recomuse-data"
    monkeypatch.setenv("RECOMUSE_DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def conn():
    """Base SQLite neuve, en mémoire, avec le schéma à jour."""
    connection = database.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def score_id(conn):
    """Une partition fictive enregistrée dans la base (aucun vrai fichier n'est utilisé)."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO scores (title, part_name, source_path, source_kind) VALUES (?, ?, ?, ?)",
            ("Morceau de test", "Flûte", "fictif/partie.pdf", "scanned_pdf"),
        )
    return cursor.lastrowid
