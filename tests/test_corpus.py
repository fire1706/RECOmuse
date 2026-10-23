"""Essais sur le corpus réel de partitions (dossier local, jamais versionné).

Ces tests sont désactivés par défaut. Pour les lancer :
    .venv\\Scripts\\python -m pytest -m corpus

Le dossier du corpus est cherché dans cet ordre : variable d'environnement
RECOMUSE_CORPUS_DIR, puis tests/corpus, puis test/corpus.
Le corpus est en LECTURE SEULE : les fichiers sont seulement ouverts et lus,
les pages produites vont dans un dossier temporaire.
"""

import os
from pathlib import Path

import pymupdf
import pytest

from recomuse.importer import preprocess
from recomuse.importer.detection import analyze_pdf_page
from recomuse.importer.loading import render_pdf_page

pytestmark = pytest.mark.corpus

# Nombre de pages examinées par fichier (pour rester rapide).
PAGES_PER_FILE = 2

REPO_ROOT = Path(__file__).resolve().parents[1]


def corpus_dir() -> Path | None:
    candidates = [os.environ.get("RECOMUSE_CORPUS_DIR"),
                  REPO_ROOT / "tests" / "corpus", REPO_ROOT / "test" / "corpus"]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


def corpus_pdfs() -> list[Path]:
    folder = corpus_dir()
    return sorted(folder.glob("*.pdf")) if folder else []


@pytest.mark.skipif(not corpus_pdfs(), reason="aucun corpus local")
@pytest.mark.parametrize("pdf", corpus_pdfs(), ids=lambda p: p.stem[:40])
def test_first_pages_are_prepared(pdf):
    with pymupdf.open(pdf) as doc:
        for page in list(doc)[:PAGES_PER_FILE]:
            analysis = analyze_pdf_page(page)
            if analysis.kind == "blank":
                continue
            pixels = render_pdf_page(page)
            if analysis.kind == "scanned":
                pixels, angle = preprocess.deskew(pixels)
                assert abs(angle) <= preprocess.MAX_SKEW_DEGREES
            metrics = preprocess.estimate_staff_metrics(pixels)
            # Les pages de texte (couverture, notice) n'ont pas de portée : on ne vérifie
            # l'interligne que lorsqu'une portée a été trouvée.
            if metrics:
                # Conducteurs : jusqu'à 6 pixels seulement à 300 dpi.
                assert 4 <= metrics.interline <= 60, analysis
