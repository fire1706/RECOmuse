"""Extraction des éléments de base d'une page PDF vectorielle.

Une page gravée contient trois sortes d'éléments :
- des CARACTÈRES de police de musique (têtes de notes, clés, silences...) → Glyph ;
- des TEXTES (titre, instrument, tempo, paroles, numéros de mesure) → TextLine ;
- des TRAITS : lignes de portée, barres de mesure, hampes, ligatures, liaisons.

Les traits sont dessinés très différemment selon le logiciel : simples segments
(Finale, la plupart du temps), rectangles pleins très fins (Sibelius), ou petits
polygones remplis (certains exports). On ne regarde donc que la FORME de chaque élément :
fin et horizontal → HLine ; fin et vertical → VLine ; épais → Shape.
En plus (tâche 4b-2) : les quadrilatères à côtés verticaux, inclinés ou non, sont gardés
avec leurs coins → Beam (ligatures) ; les tracés courbes → Curve (liaisons).
Toutes les mesures sont en points PDF (1 point = 1/72 de pouce), origine en haut à gauche.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

import pymupdf

from recomuse.importer.detection import font_base_name, is_music_font
from recomuse.vector.glyphs import (
    PERCUSSION_SYMBOLS,
    SONATA_SYMBOLS,
    SPECIAL_SYMBOLS,
    TIME_DIGITS,
    SymbolDef,
    font_role,
    glyph_code,
)

# Un trait est « fin » si son épaisseur ne dépasse pas cette valeur (points).
MAX_LINE_THICKNESS = 1.0

# Un trait est horizontal (ou vertical) s'il est au moins 3 fois plus long qu'épais.
MIN_ELONGATION = 3.0

# Un polygone rempli d'au moins 8 sommets est une courbe découpée en petits segments
# (certains exports n'écrivent pas de vraies courbes).
MIN_CURVE_VERTICES = 8

# Formes « hachurées » : certains exports remplissent une forme épaisse avec des traits
# très fins empilés (tous les 0,06 point). Des traits parallèles de même début et même
# fin, écartés de moins de STACK_GAP points, forment une seule forme, s'ils sont au
# moins MIN_STACK.
STACK_GAP = 0.15
MIN_STACK = 3


@dataclass(frozen=True)
class Glyph:
    """Un caractère de police de musique, avec son point d'ancrage sur la page."""

    code: int
    symbol: SymbolDef | None    # None : chiffre ou code inconnu
    digit: int | None           # 0 à 9 pour les chiffres, sinon None
    x: float
    y: float
    size: float                 # taille de la police, en points
    font: str
    percussion: bool = False    # caractère d'une police de percussions


@dataclass(frozen=True)
class TextLine:
    """Une ligne de texte ordinaire (lettres), avec sa boîte."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float


@dataclass(frozen=True)
class HLine:
    """Trait horizontal fin (ligne de portée, ligne supplémentaire, soulignement...)."""

    y: float
    x0: float
    x1: float


@dataclass(frozen=True)
class VLine:
    """Trait vertical fin (barre de mesure, hampe...)."""

    x: float
    y0: float
    y1: float
    thickness: float


@dataclass(frozen=True)
class Shape:
    """Forme pleine épaisse (ligature, barre de pause multiple, barre finale...)."""

    rect: pymupdf.Rect


@dataclass(frozen=True)
class Beam:
    """Bande pleine à bords gauche et droit verticaux, inclinée ou non : ligature.

    Décrite par sa ligne médiane (de (x0, y0) à (x1, y1)) et son épaisseur verticale.
    Les ligatures très fines d'un conducteur minuscule (moins d'un point) sont aussi des
    HLine pour le repérage des portées : la même forme peut figurer dans les deux listes.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    thickness: float

    def y_at(self, x: float) -> float:
        """Hauteur de la ligne médiane à l'abscisse x."""
        if self.x1 == self.x0:
            return self.y0
        return self.y0 + (self.y1 - self.y0) * (x - self.x0) / (self.x1 - self.x0)


@dataclass(frozen=True)
class Curve:
    """Tracé courbe (liaison de prolongation ou d'expression) : ses deux extrémités."""

    x0: float
    y0: float
    x1: float
    y1: float
    top: float      # point le plus haut de la courbe
    bottom: float   # point le plus bas


@dataclass
class PagePrimitives:
    glyphs: list[Glyph]
    texts: list[TextLine]
    hlines: list[HLine]
    vlines: list[VLine]
    shapes: list[Shape]
    unknown_music_fonts: list[str]   # polices sans table de correspondance utilisable
    beams: list[Beam] = field(default_factory=list)
    curves: list[Curve] = field(default_factory=list)


def _font_encodings(page: pymupdf.Page) -> dict[str, str]:
    """Codage déclaré de chaque police de la page, par nom de base.

    Une même police peut être intégrée deux fois avec des codages différents :
    on ne retient « WinAnsi » que si toutes ses copies le sont.
    """
    encodings: dict[str, set[str]] = {}
    for font in page.get_fonts():
        encodings.setdefault(font_base_name(font[3]), set()).add(font[5] or "")
    return {
        name: "WinAnsiEncoding" if values == {"WinAnsiEncoding"} else ""
        for name, values in encodings.items()
    }


def _unreadable_music_fonts(page: pymupdf.Page) -> list[str]:
    """Polices intégrées sans table de caractères (« Identity-H ») et au nom anonyme.

    Exemple du corpus : « font00000000116482c8 ». Leurs caractères ne sont que des numéros
    internes : impossible de savoir quel symbole ils représentent.
    """
    return sorted({
        font_base_name(f[3]) for f in page.get_fonts()
        if f[5] == "Identity-H" and font_base_name(f[3]).lower().startswith("font")
    })


def extract_glyphs_and_texts(page: pymupdf.Page) -> tuple[list[Glyph], list[TextLine]]:
    """Sépare les caractères de musique des textes ordinaires."""
    encodings = _font_encodings(page)
    glyphs: list[Glyph] = []
    texts: list[TextLine] = []
    # Page tournée : comme les tracés, les textes arrivent dans le repère d'origine.
    matrix = page.rotation_matrix if page.rotation else pymupdf.Identity

    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            words: list[str] = []
            boxes: list[pymupdf.Rect] = []
            sizes: list[float] = []
            for span in line["spans"]:
                base = font_base_name(span["font"])
                role = font_role(base) if is_music_font(base) else "text"
                if role == "text":
                    chunk = "".join(c["c"] for c in span["chars"])
                    if chunk.strip():
                        words.append(chunk)
                        boxes.append(pymupdf.Rect(span["bbox"]) * matrix)
                        sizes.append(span["size"])
                    continue
                for char in span["chars"]:
                    code = glyph_code(char["c"], encodings.get(base, ""))
                    if code is None or code == 0x20:
                        continue
                    table = {"symbols": SONATA_SYMBOLS, "percussion": PERCUSSION_SYMBOLS,
                             "special": SPECIAL_SYMBOLS}
                    symbol = table.get(role, {}).get(code)
                    x, y = pymupdf.Point(char["origin"]) * matrix
                    glyphs.append(Glyph(
                        code=code, symbol=symbol,
                        digit=TIME_DIGITS.get(code) if role == "symbols" else None,
                        x=x, y=y, size=span["size"], font=base,
                        percussion=role == "percussion",
                    ))
            text = " ".join(" ".join(words).split())
            if text:
                box = boxes[0]
                for other in boxes[1:]:
                    box |= other
                texts.append(TextLine(text, box.x0, box.y0, box.x1, box.y1, max(sizes)))
    return glyphs, texts


@dataclass
class _Polygon:
    vertices: list[pymupdf.Point]     # sommets (extrémités des segments et des courbes)
    points: list[pymupdf.Point]       # tous les points, y compris ceux de contrôle des courbes
    curved: bool

    @property
    def box(self) -> pymupdf.Rect:
        return pymupdf.Rect(min(p.x for p in self.points), min(p.y for p in self.points),
                            max(p.x for p in self.points), max(p.y for p in self.points))


def _polygons(items: list) -> Iterator[_Polygon]:
    """Polygones d'un tracé (les segments et courbes qui se suivent forment un polygone)."""
    current: _Polygon | None = None
    last_end: pymupdf.Point | None = None

    for item in items:
        if item[0] == "re":
            r = pymupdf.Rect(item[1])
            corners = [r.tl, r.tr, r.br, r.bl]
            yield _Polygon(corners, corners, False)
            continue
        if item[0] == "qu":
            corners = [item[1].ul, item[1].ur, item[1].lr, item[1].ll]
            yield _Polygon(corners, corners, False)
            continue
        start, end = item[1], item[-1]
        moved = last_end is not None and abs(start.x - last_end.x) + abs(start.y - last_end.y) > 0.01
        if current and moved:
            yield current
            current = None
        if current is None:
            current = _Polygon([start], [start], False)
        current.vertices.append(end)
        current.points.extend(pt for pt in item[2:] if isinstance(pt, pymupdf.Point))
        current.curved = current.curved or item[0] == "c"
        last_end = end
    if current:
        yield current


def _as_beam(polygon: _Polygon) -> Beam | None:
    """Quadrilatère dont les côtés gauche et droit sont verticaux → ligature, sinon None."""
    unique: list[pymupdf.Point] = []
    for point in polygon.vertices:
        if all(abs(point.x - u.x) + abs(point.y - u.y) > 0.01 for u in unique):
            unique.append(point)
    if len(unique) != 4:
        return None
    by_x = sorted(unique, key=lambda pt: pt.x)
    left, right = by_x[:2], by_x[2:]
    width = right[0].x - left[1].x
    if width <= 0 or abs(left[0].x - left[1].x) > 0.05 * width \
            or abs(right[0].x - right[1].x) > 0.05 * width:
        return None
    left_height = abs(left[0].y - left[1].y)
    right_height = abs(right[0].y - right[1].y)
    if left_height <= 0 or right_height <= 0 or width < 1.2 * max(left_height, right_height):
        return None
    return Beam(x0=(left[0].x + left[1].x) / 2, y0=(left[0].y + left[1].y) / 2,
                x1=(right[0].x + right[1].x) / 2, y1=(right[0].y + right[1].y) / 2,
                thickness=(left_height + right_height) / 2)


def _as_curve(points: list[pymupdf.Point], vertices: list[pymupdf.Point]) -> Curve:
    """Courbe : extrémités = sommets le plus à gauche et le plus à droite."""
    left = min(vertices, key=lambda pt: pt.x)
    right = max(vertices, key=lambda pt: pt.x)
    return Curve(left.x, left.y, right.x, right.y,
                 top=min(pt.y for pt in points), bottom=max(pt.y for pt in points))


def _classify_rect(rect: pymupdf.Rect, hlines: list, vlines: list, shapes: list) -> None:
    """Range une forme pleine selon sa forme : trait horizontal, vertical ou forme épaisse."""
    if rect.height <= MAX_LINE_THICKNESS and rect.width >= MIN_ELONGATION * max(rect.height, 0.01):
        hlines.append(HLine((rect.y0 + rect.y1) / 2, rect.x0, rect.x1))
    elif rect.width <= MAX_LINE_THICKNESS and rect.height >= MIN_ELONGATION * max(rect.width, 0.01):
        vlines.append(VLine((rect.x0 + rect.x1) / 2, rect.y0, rect.y1, rect.width))
    elif rect.width > 0 and rect.height > 0:
        shapes.append(Shape(rect))


def _rotated_items(items: list, matrix: pymupdf.Matrix) -> list:
    """Ramène les éléments d'un tracé dans le repère de la page affichée."""
    rotated = []
    for item in items:
        converted = [item[0]]
        for value in item[1:]:
            if isinstance(value, pymupdf.Point):
                converted.append(value * matrix)
            elif isinstance(value, pymupdf.Rect):
                converted.append(pymupdf.Rect(value) * matrix)
            elif isinstance(value, pymupdf.Quad):
                converted.append(value * matrix)
            else:
                converted.append(value)
        rotated.append(tuple(converted))
    return rotated


@dataclass
class _Lines:
    hlines: list[HLine] = field(default_factory=list)
    vlines: list[VLine] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    beams: list[Beam] = field(default_factory=list)
    curves: list[Curve] = field(default_factory=list)


def _extract_all_lines(page: pymupdf.Page) -> _Lines:
    """Range tous les tracés de la page (voir extract_lines)."""
    out = _Lines()
    thin_strokes: list[tuple[pymupdf.Point, pymupdf.Point, float]] = []
    matrix = page.rotation_matrix if page.rotation else None
    for drawing in page.get_drawings():
        filled = "f" in (drawing.get("type") or "")
        thickness = drawing.get("width") or 0.0
        if matrix is not None:
            drawing = {**drawing, "items": _rotated_items(drawing["items"], matrix)}
        if filled:
            for polygon in _polygons(drawing["items"]):
                if polygon.curved or len(polygon.vertices) >= MIN_CURVE_VERTICES:
                    out.curves.append(_as_curve(polygon.points, polygon.vertices))
                    continue
                _classify_rect(polygon.box, out.hlines, out.vlines, out.shapes)
                beam = _as_beam(polygon)
                if beam is not None:
                    out.beams.append(beam)
            continue
        for item in drawing["items"]:
            if item[0] == "l":
                p, q = item[1], item[2]
                if thickness > MAX_LINE_THICKNESS:
                    # Trait épais (ligature, barre de pause multiple, barre finale).
                    half = thickness / 2
                    out.shapes.append(Shape(pymupdf.Rect(min(p.x, q.x) - half,
                                                         min(p.y, q.y) - half,
                                                         max(p.x, q.x) + half,
                                                         max(p.y, q.y) + half)))
                    if abs(q.x - p.x) > 2 * thickness:
                        left, right = (p, q) if p.x < q.x else (q, p)
                        out.beams.append(Beam(left.x, left.y, right.x, right.y, thickness))
                elif abs(p.y - q.y) < 0.05 and abs(q.x - p.x) > 0:
                    out.hlines.append(HLine((p.y + q.y) / 2, min(p.x, q.x), max(p.x, q.x)))
                    thin_strokes.append((p, q, thickness))
                elif abs(p.x - q.x) >= 0.05 and abs(q.y - p.y) >= 0.05:
                    thin_strokes.append((p, q, thickness))
                elif abs(p.x - q.x) < 0.05 and abs(q.y - p.y) > 0:
                    out.vlines.append(VLine((p.x + q.x) / 2, min(p.y, q.y), max(p.y, q.y),
                                            thickness))
            elif item[0] == "re":
                # Rectangle seulement tracé : il compte s'il est assez fin pour être un trait.
                rect = pymupdf.Rect(item[1])
                if min(rect.width, rect.height) <= MAX_LINE_THICKNESS:
                    _classify_rect(rect, out.hlines, out.vlines, out.shapes)
            elif item[0] == "c":
                # Liaison dessinée d'un seul trait (non remplie).
                points = [pt for pt in item[1:] if isinstance(pt, pymupdf.Point)]
                out.curves.append(_as_curve(points, [item[1], item[-1]]))
    for beam in _stacked_strokes(thin_strokes):
        out.beams.append(beam)
        half = beam.thickness / 2
        out.shapes.append(Shape(pymupdf.Rect(beam.x0, min(beam.y0, beam.y1) - half,
                                             beam.x1, max(beam.y0, beam.y1) + half)))
    return out


def _stacked_strokes(strokes: list[tuple[pymupdf.Point, pymupdf.Point, float]]) -> list[Beam]:
    """Regroupe les traits fins parallèles empilés (forme hachurée) en formes épaisses."""
    groups: dict[tuple[float, float, float], list[tuple[float, float, float]]] = {}
    for p, q, width in strokes:
        left, right = (p, q) if p.x <= q.x else (q, p)
        slope = (right.y - left.y) / (right.x - left.x) if right.x != left.x else 0.0
        key = (round(left.x, 1), round(right.x, 1), round(slope, 2))
        groups.setdefault(key, []).append((left.y, right.y, width))

    beams = []
    for (x0, x1, _), lines in groups.items():
        lines.sort()
        stack = [lines[0]]
        for line in lines[1:] + [None]:
            if line is not None and line[0] - stack[-1][0] <= STACK_GAP:
                stack.append(line)
                continue
            if len(stack) >= MIN_STACK:
                width = stack[0][2]
                span = stack[-1][0] - stack[0][0] + width
                beams.append(Beam(x0, (stack[0][0] + stack[-1][0]) / 2,
                                  x1, (stack[0][1] + stack[-1][1]) / 2, span))
            if line is not None:
                stack = [line]
    return beams


def extract_lines(page: pymupdf.Page) -> tuple[list[HLine], list[VLine], list[Shape]]:
    """Range tous les tracés de la page en traits horizontaux, verticaux et formes épaisses.

    Page enregistrée tournée (ex. conducteur à l'italienne, rotation 270°) : PyMuPDF donne
    les tracés dans le repère d'origine, non tourné, où les portées sont verticales.
    On les ramène dans le repère de la page affichée (voir aussi extract_glyphs_and_texts).
    """
    lines = _extract_all_lines(page)
    return lines.hlines, lines.vlines, lines.shapes


def extract_primitives(page: pymupdf.Page) -> PagePrimitives:
    glyphs, texts = extract_glyphs_and_texts(page)
    lines = _extract_all_lines(page)
    return PagePrimitives(glyphs, texts, lines.hlines, lines.vlines, lines.shapes,
                          _unreadable_music_fonts(page), lines.beams, lines.curves)
