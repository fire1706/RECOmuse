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
from recomuse.vector import read_vector_pdf

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


@pytest.mark.skipif(not corpus_pdfs(), reason="aucun corpus local")
@pytest.mark.parametrize("pdf", corpus_pdfs(), ids=lambda p: p.stem[:40])
def test_vector_reading_does_not_fail(pdf):
    """Lecture vectorielle des 3 premières pages : pas d'erreur, et des portées trouvées
    sur toute page vectorielle lisible."""
    score = read_vector_pdf(pdf, [n for n in (1, 2, 3) if n <= pymupdf.open(pdf).page_count])
    for page in score.pages:
        assert page.systems


# Résultats vérifiés à l'œil sur le corpus (tâche 4b-1) : ils ne doivent pas se dégrader.
# Clé : début du nom de fichier ; valeurs : pages lues et résumé attendu de la 1re partie.
EXPECTED_VECTOR = {
    "throwin_down": ([1], {"time_changes": [(1, "4/4")], "key_changes": [(1, 1)],
                           "multirests": [(2, 12)]}),
    "Michael Buble": ([1, 2, 3], {"time_changes": [(1, "4/4")],
                                  "key_changes": [(1, -3), (53, 4)]}),
    "Monty Norman": ([1, 2, 3], {"measure_count": 31, "time_changes": [(1, "4/4")],
                                 "key_changes": [(1, -1)]}),
    "Paul Anka": ([1, 2, 3], {"measure_count": 22, "multirests": []}),
}


@pytest.mark.parametrize("prefix", sorted(EXPECTED_VECTOR))
def test_vector_reading_known_results(prefix):
    matches = [p for p in corpus_pdfs() if p.name.startswith(prefix)]
    if not matches:
        pytest.skip(f"{prefix} absent du corpus")
    pages, expected = EXPECTED_VECTOR[prefix]
    summary = read_vector_pdf(matches[0], pages).to_dict()
    for key, value in expected.items():
        assert summary[key] == value, key
