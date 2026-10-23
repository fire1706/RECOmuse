"""Tests du repérage des portées, des barres de mesure et des systèmes."""

from recomuse.vector.primitives import HLine, VLine
from recomuse.vector.staves import find_barlines, find_staves, group_systems, merge_rows

from vector_builder import BLACK, PageBuilder


def test_pieces_of_a_line_are_merged():
    pieces = [HLine(100, 50, 150), HLine(100.1, 150.5, 300), HLine(100, 400, 500)]
    merged = merge_rows(pieces)
    assert [(round(l.x0), round(l.x1)) for l in merged] == [(50, 300), (400, 500)]


def test_staff_drawn_in_pieces_is_found():
    page = PageBuilder()
    page.staff(100, pieces=6)
    staves = find_staves(page.build().hlines)
    assert len(staves) == 1
    assert staves[0].interline == 5.0
    assert (staves[0].x0, staves[0].x1) == (50, 550)


def test_doubled_lines_are_ignored():
    """Ligne épaisse dessinée par son contour : deux traits à 0,2 point d'écart."""
    page = PageBuilder()
    page.staff(100)
    page.hlines += [HLine(l.y + 0.2, l.x0, l.x1) for l in list(page.hlines)]
    assert len(find_staves(page.build().hlines)) == 1


def test_irregular_lines_are_not_a_staff():
    lines = [HLine(y, 50, 550) for y in (100, 105, 110, 118, 120)]
    assert find_staves(lines) == []


def test_ledger_lines_are_ignored():
    page = PageBuilder()
    page.staff(100)
    page.hlines += [HLine(95, 200, 208), HLine(90, 200, 208)]  # lignes supplémentaires
    assert len(find_staves(page.build().hlines)) == 1


def test_tiny_conductor_staff():
    page = PageBuilder()
    page.staff(100, interline=1.5)
    assert find_staves(page.build().hlines)[0].interline == 1.5


def test_barlines_and_stems():
    page = PageBuilder()
    page.staff(100, barlines=[200, 350, 550])
    # Une note sur la ligne du bas, hampe vers le haut couvrant toute la portée : ce
    # n'est pas une barre de mesure.
    page.note(0, 260, 0)
    page.vlines.append(VLine(260 + 6, 100, 120, 0.5))
    prims = page.build()
    staves = find_staves(prims.hlines)
    heads = [g for g in prims.glyphs if g.code == BLACK]
    find_barlines(staves, prims.vlines, prims.shapes, heads)
    assert staves[0].barlines == [200, 350, 550]


def test_double_barline_counts_once():
    page = PageBuilder()
    page.staff(100, barlines=[300, 302.5, 550])
    prims = page.build()
    staves = find_staves(prims.hlines)
    find_barlines(staves, prims.vlines, prims.shapes, [])
    assert staves[0].barlines == [302.5, 550]


def test_systems_of_a_conductor_score():
    page = PageBuilder()
    for top in (100, 140, 180):           # système 1 : 3 portées reliées
        page.staff(top, barlines=[])
    for top in (300, 340, 380):           # système 2
        page.staff(top, barlines=[])
    page.vlines += [VLine(50, 100, 200, 0.5), VLine(300, 100, 200, 0.5),
                    VLine(50, 300, 400, 0.5)]
    prims = page.build()
    staves = find_staves(prims.hlines)
    found = find_barlines(staves, prims.vlines, prims.shapes, [])
    assert group_systems(staves, found) == [[0, 1, 2], [3, 4, 5]]


def test_separate_parts_are_separate_systems():
    page = PageBuilder()
    page.staff(100)
    page.staff(160)
    prims = page.build()
    staves = find_staves(prims.hlines)
    found = find_barlines(staves, prims.vlines, prims.shapes, [])
    assert group_systems(staves, found) == [[0], [1]]


def test_two_pages_side_by_side_are_read_column_by_column():
    """Feuille à l'italienne avec deux pages : le système de droite commence plus haut
    (pas de titre) mais vient après celui de gauche."""
    page = PageBuilder()
    page.staff(150, x0=40, x1=380)     # page de gauche (sous le titre)
    page.staff(60, x0=440, x1=800)     # page de droite
    prims = page.build()
    staves = find_staves(prims.hlines)
    found = find_barlines(staves, prims.vlines, prims.shapes, [])
    systems = group_systems(staves, found)
    assert [staves[s[0]].x0 for s in systems] == [40, 440]
