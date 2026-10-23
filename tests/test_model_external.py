"""De bout en bout avec le vrai Audiveris : import, reconnaissance, modèle, correction.

Lancé sur demande :  .venv\\Scripts\\python -m pytest -m external
"""

import pymupdf
import pytest

from recomuse.importer import import_score, register_score
from recomuse.importer.loading import render_pdf_page
from recomuse.learning.corrections import CorrectionService
from recomuse.model.build import build_model
from recomuse.model.store import load_model, save_model
from recomuse.recognition import recognize_score, tools

from synthetic import part_pdf, scanned_pdf

real_tools = tools.check_tools()


@pytest.mark.external
@pytest.mark.skipif(real_tools.audiveris is None, reason="Audiveris n'est pas installé")
def test_scanned_part_end_to_end(tmp_path, conn, monkeypatch):
    if real_tools.tessdata:
        monkeypatch.setenv("RECOMUSE_TESSDATA", str(real_tools.tessdata))
    # Partie synthétique, « scannée » : la page vectorielle devient une image pleine page.
    with pymupdf.open(part_pdf(tmp_path / "partie.pdf")) as doc:
        image = render_pdf_page(doc[0], 200)
    score = import_score(scanned_pdf(tmp_path / "scan.pdf", [image]), tmp_path / "work")
    recognition = recognize_score(score)
    model = build_model(score, recognition)

    part = model.parts[0]
    assert sum(m.length for m in part.measures) == 24
    notes = [s for m in part.measures for s in m.events if s.kind == "note"]
    assert len(notes) >= 80
    # Positions et confiances viennent du projet .omr d'Audiveris.
    located = [s for s in notes if s.bbox is not None and s.confidence != 0.5]
    assert len(located) >= 0.9 * len(notes)
    assert all(s.source == "audiveris" for s in notes)

    score_id = register_score(conn, score)
    save_model(conn, score_id, model)
    service = CorrectionService(conn, snippets_dir=tmp_path / "extraits")
    target = notes[0]
    service.apply(score_id, target.id, {"octave": target.value["octave"] + 1}, source="question")
    corrected = load_model(conn, score_id).find(target.id)[2]
    assert corrected.value["octave"] == target.value["octave"] + 1
    history = service.history(score_id, target.id)
    assert len(history) == 1 and (tmp_path / "extraits" / history[0].snippet_path).is_file()
