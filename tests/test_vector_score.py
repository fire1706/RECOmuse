"""Tests de l'extraction des traits d'un vrai PDF, et de la lecture d'un PDF entier."""

import pymupdf
import pytest

from recomuse.vector import read_vector_pdf
from recomuse.vector.primitives import extract_glyphs_and_texts, extract_lines
from recomuse.vector.reader import Measure, StaffContent, VectorPage
from recomuse.vector.score import VectorScore
from recomuse.vector.staves import Staff, find_staves

from synthetic import scanned_pdf, staff_page, vector_pdf

# --- Traits extraits d'un PDF ------------------------------------------------------------


def draw_staff(page, top, kind, interline=5.0):
    """Portée dessinée de trois façons, comme le font différents logiciels."""
    for k in range(5):
        y = top + k * interline
        if kind == "lines":          # Finale : segments tracés
            page.draw_line((50, y), (550, y), width=0.5)
        elif kind == "thin_rects":   # Sibelius : rectangles pleins très fins, par mesure
            for x0 in (50, 300):
                page.draw_rect(pymupdf.Rect(x0, y - 0.2, x0 + 250, y + 0.2),
                               color=None, fill=(0, 0, 0))
        elif kind == "polygons":     # export : polygones remplis
            page.draw_polyline([(50, y - 0.2), (550, y - 0.2), (550, y + 0.2), (50, y + 0.2)],
                               color=None, fill=(0, 0, 0), closePath=True)


@pytest.mark.parametrize("kind", ["lines", "thin_rects", "polygons"])
def test_staff_lines_drawn_in_different_ways(tmp_path, kind):
    doc = pymupdf.open()
    page = doc.new_page()
    draw_staff(page, 100, kind)
    page.draw_line((300, 100), (300, 120), width=0.5)        # barre de mesure
    page.draw_line((50, 200), (200, 200), width=2.5)          # trait épais (pause multiple)
    hlines, vlines, shapes = extract_lines(page)

    staves = find_staves(hlines)
    assert len(staves) == 1
    assert staves[0].interline == pytest.approx(5.0, abs=0.05)
    assert (round(staves[0].x0), round(staves[0].x1)) == (50, 550)
    assert any(abs(v.x - 300) < 0.1 for v in vlines)
    assert any(s.rect.width > 140 and s.rect.height > 2 for s in shapes)


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_page_gives_the_displayed_layout(rotation):
    """Conducteur à l'italienne enregistré tourné : dans le PDF, tout est écrit dans le
    repère d'origine (portées verticales) ; à l'écran, les portées sont horizontales.
    La lecture doit se faire dans le repère affiché, pour les traits comme pour les textes."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(rotation)
    to_pdf = page.derotation_matrix          # repère affiché → repère d'origine du PDF
    for k in range(5):
        y = 100 + 5 * k
        page.draw_line(pymupdf.Point(50, y) * to_pdf, pymupdf.Point(550, y) * to_pdf, width=0.5)
    page.insert_text(pymupdf.Point(60, 90) * to_pdf, "Flute", fontsize=10, rotate=rotation)

    hlines, _, _ = extract_lines(page)
    staves = find_staves(hlines)
    _, texts = extract_glyphs_and_texts(page)
    assert len(staves) == 1
    staff = staves[0]
    assert (round(staff.x0), round(staff.x1), round(staff.top)) == (50, 550, 100)
    text = texts[0]
    assert text.text == "Flute"
    # Le texte est juste au-dessus du début de la portée, dans le même repère.
    assert staff.x0 - 20 <= text.x0 <= staff.x0 + 20
    assert 0 <= staff.top - text.y1 < 20


def test_texts_are_grouped_by_line(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((100, 50), "Alto Saxophone 1", fontsize=12)
    _, texts = extract_glyphs_and_texts(page)
    assert [t.text for t in texts] == ["Alto Saxophone 1"]


# --- PDF entier --------------------------------------------------------------------------


def test_read_vector_pdf_skips_scanned_pages(tmp_path):
    """Un PDF de test (portées tracées, sans police de musique) et un PDF scanné."""
    vector = read_vector_pdf(vector_pdf(tmp_path / "v.pdf", page_count=2))
    assert [p.page_number for p in vector.pages] == [1, 2]
    assert vector.staff_count == 1
    assert "no_clef" in vector.warnings

    scanned = read_vector_pdf(scanned_pdf(tmp_path / "s.pdf", [staff_page()]))
    assert scanned.pages == []


def test_read_selected_pages(tmp_path):
    vector = read_vector_pdf(vector_pdf(tmp_path / "v.pdf", page_count=3), [2])
    assert [p.page_number for p in vector.pages] == [2]


def make_score(systems_per_page):
    """Partition fabriquée : une liste de pages, chaque page une liste de systèmes,
    chaque système une liste de mesures (une seule portée)."""
    staff = Staff([0, 5, 10, 15, 20], 0, 500)
    pages = [
        VectorPage(n, [[StaffContent(staff, measures)] for measures in systems], [], [])
        for n, systems in enumerate(systems_per_page, start=1)
    ]
    return VectorScore(source_path=None, pages=pages)


def bar(**fields):
    return Measure(0, 100, **fields)


def test_part_measures_numbering_and_changes():
    score = make_score([
        [[bar(time_signature="4/4", key_fifths=-1), bar(is_multirest=True, multirest=12)],
         [bar(key_fifths=-1), bar(time_signature="3/4")]],
        [[bar(key_fifths=2, time_signature="3/4"), bar()]],
    ])
    numbers = [m.number for m in score.part_measures()]
    assert numbers == [1, 2, 14, 15, 16, 17]
    assert score.measure_count() == 17
    assert score.time_changes() == [(1, "4/4"), (15, "3/4")]
    # L'armure répétée en début de ligne n'est pas un changement.
    assert score.key_changes() == [(1, -1), (16, 2)]
    assert score.multirests() == [(2, 12)]
    assert [m.page for m in score.part_measures()] == [1, 1, 1, 1, 2, 2]
    assert score.to_dict()["measure_count"] == 17


def test_multirest_without_number_counts_as_one_measure():
    score = make_score([[[bar(), bar(is_multirest=True, multirest=None), bar()]]])
    assert score.measure_count() == 3
