"""Outils partagés par les tests Python (« fixtures » pytest)."""

import sys
from pathlib import Path

import pytest

from recomuse.recognition import audiveris, ocr
from recomuse.storage import database

# Faux programmes externes (voir tests/fakes/) : les tests n'ont besoin ni d'Audiveris
# ni de Tesseract. Les tests marqués « external » utilisent les vrais.
FAKES_DIR = Path(__file__).parent / "fakes"


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


@pytest.fixture
def fake_audiveris(monkeypatch):
    """Remplace Audiveris par tests/fakes/fake_audiveris.py (mêmes arguments)."""
    real_command = audiveris.audiveris_command

    def command(exe, book_path, output_dir, tessdata):
        return [sys.executable, str(FAKES_DIR / "fake_audiveris.py"),
                *real_command(exe, book_path, output_dir, tessdata)[1:]]
    monkeypatch.setattr(audiveris, "audiveris_command", command)
    return Path("Audiveris.exe")


@pytest.fixture
def fake_tesseract(monkeypatch):
    """Remplace Tesseract par tests/fakes/fake_tesseract.py (mêmes arguments)."""
    real_command = ocr.tesseract_command

    def command(exe, image, tessdata):
        return [sys.executable, str(FAKES_DIR / "fake_tesseract.py"),
                *real_command(exe, image, tessdata)[1:]]
    monkeypatch.setattr(ocr, "tesseract_command", command)
    return Path("tesseract.exe")
