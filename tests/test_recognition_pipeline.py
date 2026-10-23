"""Tests de la reconnaissance complète.

- Avec les faux programmes (tests/fakes/) : toujours lancés.
- Avec les vrais Audiveris et Tesseract : marqués « external », lancés sur demande :
      .venv\\Scripts\\python -m pytest -m external
"""

import json
from pathlib import Path

import pytest

from recomuse.importer import import_score
from recomuse.recognition import RecognitionResult, recognize_score, tools
from recomuse.recognition.audiveris import AudiverisError
from recomuse.recognition.tools import ToolNotFoundError, ToolsStatus

from synthetic import part_pdf, scanned_pdf, staff_page


@pytest.fixture
def tessdata(tmp_path):
    folder = tmp_path / "tessdata"
    folder.mkdir()
    for lang in tools.OCR_LANGUAGES:
        (folder / f"{lang}.traineddata").write_bytes(b"")
    return folder


def set_tools(monkeypatch, audiveris=None, tesseract=None, tessdata=None, missing=()):
    """Fait croire au pipeline que ces programmes sont installés."""
    status = ToolsStatus(audiveris=audiveris, tesseract=tesseract, tessdata=tessdata,
                         languages=[], missing_languages=list(missing))
    monkeypatch.setattr(tools, "check_tools", lambda: status)


@pytest.fixture
def imported(tmp_path):
    """Partition scannée de 3 pages : couverture sans portée, puis 2 pages de musique."""
    import numpy as np

    cover = np.full((1000, 700), 255, np.uint8)
    path = scanned_pdf(tmp_path / "partie.pdf", [cover, staff_page(), staff_page()])
    return import_score(path, tmp_path / "work")


def test_full_recognition_with_fakes(imported, tessdata, monkeypatch, fake_audiveris,
                                     fake_tesseract):
    set_tools(monkeypatch, audiveris=fake_audiveris, tesseract=fake_tesseract, tessdata=tessdata)
    progress = []
    result = recognize_score(imported, on_progress=lambda d, t: progress.append(d / t))

    assert isinstance(result, RecognitionResult)
    # La couverture (page 1) n'est pas envoyée à Audiveris.
    assert result.run.book.sheet_pages == [2, 3]
    assert result.run.output_dir == imported.work_dir / "audiveris"
    assert len(result.movements) == 2
    assert result.measure_count == 4
    assert result.movement_pages(result.movements[1]) == [3]
    assert progress[-1] == 1.0
    # En-tête lu par le faux Tesseract.
    assert result.header.title == "MARCHE D'ACOZ"
    assert result.header.instrument == "Flûte 1"
    assert result.header.tempo == "Allegro"
    assert result.header.composers == ["arr. J. Dupont"]
    assert result.warnings == []
    # Tout le résultat passe en JSON (pour l'interface).
    data = json.loads(json.dumps(result.to_dict()))
    assert data["movements"][0]["pages"] == [2]


def test_without_tesseract_audiveris_texts_are_used(imported, monkeypatch, fake_audiveris):
    set_tools(monkeypatch, audiveris=fake_audiveris)
    result = recognize_score(imported)
    assert result.warnings == ["ocr_unavailable"]
    # Le faux Audiveris a lu « Marche de test » en crédit.
    assert result.header.title == "Marche de test"


def test_tesseract_failure_is_a_warning(imported, tessdata, monkeypatch, fake_audiveris,
                                        fake_tesseract):
    monkeypatch.setenv("FAKE_TESSERACT_MODE", "fail")
    set_tools(monkeypatch, audiveris=fake_audiveris, tesseract=fake_tesseract, tessdata=tessdata)
    result = recognize_score(imported)
    assert result.warnings == ["ocr_failed"]
    assert result.measure_count == 4


def test_missing_languages_are_reported(imported, tessdata, monkeypatch, fake_audiveris,
                                        fake_tesseract):
    set_tools(monkeypatch, audiveris=fake_audiveris, tesseract=fake_tesseract, tessdata=tessdata,
              missing=["nld"])
    assert "ocr_languages_missing" in recognize_score(imported).warnings


def test_audiveris_is_required(imported, monkeypatch):
    set_tools(monkeypatch, audiveris=None)
    with pytest.raises(ToolNotFoundError) as info:
        recognize_score(imported)
    assert info.value.code == "audiveris_not_found"


def test_score_without_music(tmp_path, monkeypatch, fake_audiveris):
    import numpy as np

    set_tools(monkeypatch, audiveris=fake_audiveris)
    score = import_score(scanned_pdf(tmp_path / "c.pdf", [np.full((900, 600), 255, np.uint8)]),
                         tmp_path / "work")
    with pytest.raises(AudiverisError) as info:
        recognize_score(score)
    assert info.value.code == "no_music_recognized"


# --- Avec les vrais programmes -----------------------------------------------------------

real_tools = tools.check_tools()


@pytest.mark.external
@pytest.mark.skipif(not (real_tools.audiveris and real_tools.tesseract and real_tools.tessdata),
                    reason="Audiveris, Tesseract ou les langues ne sont pas installés")
def test_real_tools_on_a_synthetic_part(tmp_path, monkeypatch):
    # Les tests utilisent un dossier de données temporaire : on y indique les vraies langues.
    monkeypatch.setenv("RECOMUSE_TESSDATA", str(real_tools.tessdata))
    score = import_score(part_pdf(Path(tmp_path) / "partie.pdf"), tmp_path / "work")
    result = recognize_score(score)

    assert result.header.title == "MARCHE D'ACOZ"
    assert result.header.instrument == "Flute 1"
    assert result.header.tempo == "Allegro"
    assert result.header.composers == ["arr. J. Dupont"]
    # 6 systèmes de 4 mesures.
    assert result.measure_count == 24
    assert result.run.omr_path is not None
