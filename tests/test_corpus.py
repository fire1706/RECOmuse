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


# Tâche 4b-2 : sur ces pages (une seule partie à chaque fois), toutes les mesures ont la
# durée de leur chiffrage, et la numérotation calculée correspond aux numéros imprimés.
EXACT_RHYTHMS = {
    "Michael Buble": [1, 2, 3], "Monty Norman": [1, 2, 3], "Paul Anka": [1, 2, 3],
    "Miklos": [1, 2, 3], "blues_on_the_hill--": [1, 2],
    "throwin_down": [1, 2],   # la page 3 commence la partie suivante
}


@pytest.mark.parametrize("prefix", sorted(EXACT_RHYTHMS))
def test_vector_rhythms_and_numbering(prefix):
    matches = [p for p in corpus_pdfs() if p.name.startswith(prefix)]
    if not matches:
        pytest.skip(f"{prefix} absent du corpus")
    score = read_vector_pdf(matches[0], EXACT_RHYTHMS[prefix])
    assert score.duration_mismatches() == []
    for item in score.part_measures():
        if item.measure.printed_number is not None:
            assert item.measure.printed_number == item.number


def test_model_of_a_vector_part_without_audiveris(tmp_path, monkeypatch):
    """Tâche 5 : une partie vectorielle donne un modèle complet sans lancer Audiveris."""
    from recomuse.importer import import_score
    from recomuse.model.build import build_model
    from recomuse.recognition import recognize_score, tools

    matches = [p for p in corpus_pdfs() if p.name.startswith("throwin_down")]
    if not matches:
        pytest.skip("throwin_down absent du corpus")
    # Même sans Audiveris installé, tout doit fonctionner.
    status = tools.check_tools()
    monkeypatch.setattr(tools, "check_tools", lambda: tools.ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[],
        missing_languages=status.missing_languages))
    score = import_score(matches[0], tmp_path / "work")
    score.pages = [p for p in score.pages if p.page_number <= 2]
    recognition = recognize_score(score)
    assert recognition.run is None
    model = build_model(score, recognition)
    assert sum(m.length for m in model.parts[0].measures) == 109
    assert all(s.bbox is not None for s in model.symbols())
    assert model.title == "Throwin' Down" and model.instrument == "Alto Saxophone 1"


def test_validator_catches_audiveris_errors(tmp_path, monkeypatch):
    """Tâche 6 : la partie de saxophone alto de « Throwin' Down » lue par Audiveris (au lieu
    de la lecture vectorielle exacte) contient les erreurs du test de faisabilité : le
    validateur doit les trouver."""
    from recomuse.importer import import_score
    from recomuse.model.build import build_model
    from recomuse.recognition import recognize_score, tools
    from recomuse.validation import validate

    matches = [p for p in corpus_pdfs() if p.name.startswith("throwin_down")]
    status = tools.check_tools()
    if not matches or status.audiveris is None:
        pytest.skip("throwin_down ou Audiveris absent")
    if status.tessdata:
        monkeypatch.setenv("RECOMUSE_TESSDATA", str(status.tessdata))
    score = import_score(matches[0], tmp_path / "work")
    score.pages = [p for p in score.pages if p.page_number <= 2]
    recognition = recognize_score(score, audiveris_for_vector_pages=True)
    recognition.vector = None
    model = build_model(score, recognition)
    report = validate(model)

    codes = {i.code for i in report.issues}
    # Clé de sol lue octaviée : toute la partie une octave trop bas.
    assert "clef_octave_suspicious" in codes
    # Chiffrage « C » perdu.
    assert "time_signature_missing" in codes
    # Pauses multiples de 12 et 8 mesures lues comme des mesures vides.
    assert len(report.by_code("multirest_missed")) == 2


# Tâche 7 : PDF contenant toutes les parties d'un morceau. Nombre de parties trouvées,
# longueur habituelle, et écarts attendus (partie, code, correction proposée).
GROUPED_PARTS = {
    "blues_on_the_hill--": (16, 156, []),
    # Ténor 1 : pause de 8 mesures dessinée avec un signe inhabituel, lue comme une mesure.
    # Trompette 2 : une pause d'une mesure là où les autres parties en ont deux.
    "throwin_down": (17, 109, [("Tenor Saxophone 1", "part_measures_missing", 8),
                               ("Trumpet in B 2", "part_measures_missing", 2)]),
}


@pytest.mark.parametrize("prefix", sorted(GROUPED_PARTS))
def test_grouped_parts_are_split_and_compared(tmp_path, monkeypatch, prefix):
    from recomuse.importer import import_score
    from recomuse.model.build import build_model
    from recomuse.model.split import split_parts
    from recomuse.recognition import recognize_score, tools
    from recomuse.validation.comparison import compare_parts, part_refs

    matches = [p for p in corpus_pdfs() if p.name.startswith(prefix)]
    if not matches:
        pytest.skip(f"{prefix} absent du corpus")
    status = tools.check_tools()
    monkeypatch.setattr(tools, "check_tools", lambda: tools.ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[],
        missing_languages=status.missing_languages))
    score = import_score(matches[0], tmp_path / "work")
    recognition = recognize_score(score)
    models = split_parts(build_model(score, recognition), recognition.page_headers)
    refs = part_refs(models)
    count, usual, expected = GROUPED_PARTS[prefix]
    assert len(refs) == count
    report = compare_parts(refs)
    found = [(i.part_id, i.code, i.action.get("set_multirest")) for i in report.issues]
    assert found == expected
    assert all(i.details["usual_length"] == usual for i in report.issues)


def test_conductor_of_blues_on_the_hill(tmp_path, monkeypatch, conn):
    """Tâche 14 : le conducteur est lu avec le nom de chaque instrument, et ses parties
    extraites ont la même longueur que les parties séparées du même morceau."""
    from recomuse import library
    from recomuse.recognition import tools

    matches = [p for p in corpus_pdfs() if p.name.startswith("blues_on_the_hill_score")]
    if not matches:
        pytest.skip("conducteur absent du corpus")
    status = tools.check_tools()
    monkeypatch.setattr(tools, "check_tools", lambda: tools.ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[],
        missing_languages=status.missing_languages))
    [score] = library.open_file(conn, matches[0], work_root=tmp_path / "work")
    assert score["instruments"][:5] == ["Alto Sax 1", "Alto Sax 2", "Tenor Sax 1",
                                        "Tenor Sax 2", "Baritone Sax"]
    assert score["instruments"][-3:] == ["Piano", "Bass", "Drums"]
    parts = library.extract_parts(conn, score["score_id"])
    assert len(parts) == 17                          # 18 portées, le piano en a deux
    assert {p["measure_count"] for p in parts} == {156}
    piano = next(p for p in parts if p["instrument"] == "Piano")
    assert piano["derived"] == "extracted"
