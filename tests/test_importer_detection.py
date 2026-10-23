"""Tests de la détection du type des pages PDF."""

import pymupdf
import pytest

from recomuse.importer.detection import (
    PageAnalysis,
    analyze_pdf_page,
    document_kind,
    font_base_name,
    is_music_font,
)

from synthetic import scanned_pdf, staff_page, vector_pdf


@pytest.mark.parametrize("name", [
    "EDWLKR+Maestro", "CXOYBI+MaestroPercussion", "MEYSSI+Petrucci", "URBCRX+Jazz",
    "MWVCHF+JazzText", "DGAKDK+Opus", "FPLVIL+Inkpen2", "WQWQPF+BroadwayCopyistText",
    "Bravura", "Leland", "Emmentaler-20", "Finale Maestro",
])
def test_music_fonts_are_recognised(name):
    assert is_music_font(name)


@pytest.mark.parametrize("name", [
    "TimesNewRomanPSMT", "DCQLVO+Helvetica", "ArialMT", "KNDMQW+TrebuchetMS", "CentaurMT",
])
def test_text_fonts_are_not_music_fonts(name):
    assert not is_music_font(name)


def test_font_base_name_removes_subset_prefix():
    assert font_base_name("EDWLKR+Maestro") == "Maestro"
    assert font_base_name("Maestro") == "Maestro"


def analyze_first_page(path):
    with pymupdf.open(path) as doc:
        return analyze_pdf_page(doc[0])


def test_vector_page(tmp_path):
    analysis = analyze_first_page(vector_pdf(tmp_path / "v.pdf"))
    assert analysis.kind == "vector"
    assert analysis.page_number == 1
    assert analysis.drawing_count > 0
    assert analysis.image_coverage == 0
    assert analysis.source_dpi is None


def test_scanned_page_and_its_resolution(tmp_path):
    analysis = analyze_first_page(scanned_pdf(tmp_path / "s.pdf", [staff_page(dpi=150)]))
    assert analysis.kind == "scanned"
    assert analysis.image_coverage == pytest.approx(1.0, abs=0.01)
    assert analysis.source_dpi == pytest.approx(150, abs=2)


def test_ocr_text_layer_does_not_make_a_scan_vector(tmp_path):
    path = scanned_pdf(tmp_path / "ocr.pdf", [staff_page(dpi=150)], ocr_text="Flute 1")
    analysis = analyze_first_page(path)
    assert analysis.text_length > 0
    assert analysis.kind == "scanned"


def test_blank_page(tmp_path):
    assert analyze_first_page(scanned_pdf(tmp_path / "b.pdf", [None])).kind == "blank"


def page(kind):
    return PageAnalysis(page_number=1, kind=kind, image_coverage=0, source_dpi=None,
                        drawing_count=0, text_length=0)


def test_document_kind_follows_the_majority():
    assert document_kind([page("vector")] * 3 + [page("scanned")]) == "vector_pdf"
    assert document_kind([page("scanned")] * 2 + [page("vector")]) == "scanned_pdf"


def test_document_kind_ignores_blank_pages_and_prefers_scanned_on_tie():
    assert document_kind([page("vector"), page("blank"), page("blank")]) == "vector_pdf"
    assert document_kind([page("vector"), page("scanned")]) == "scanned_pdf"
