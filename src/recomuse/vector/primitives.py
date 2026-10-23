"""Extraction des éléments de base d'une page PDF vectorielle.

Une page gravée contient trois sortes d'éléments :
- des CARACTÈRES de police de musique (têtes de notes, clés, silences...) → Glyph ;
- des TEXTES (titre, instrument, tempo, paroles, numéros de mesure) → TextLine ;
- des TRAITS : lignes de portée, barres de mesure, hampes, ligatures, liaisons.

Les traits sont dessinés très différemment selon le logiciel : simples segments
(Finale, la plupart du temps), rectangles pleins très fins (Sibelius), ou petits
polygones remplis (certains exports). On ne regarde donc que la FORME de chaque élément :
fin et horizontal → HLine ; fin et vertical → VLine ; épais → Shape.
Toutes les mesures sont en points PDF (1 point = 1/72 de pouce), origine en haut à gauche.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import pymupdf

from recomuse.importer.detection import font_base_name, is_music_font
from recomuse.vector.glyphs import SONATA_SYMBOLS, TIME_DIGITS, SymbolDef, font_role, glyph_code

# Un trait est « fin » si son épaisseur ne dépasse pas cette valeur (points).
MAX_LINE_THICKNESS = 1.0

# Un trait est horizontal (ou vertical) s'il est au moins 3 fois plus long qu'épais.
MIN_ELONGATION = 3.0


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


@dataclass
class PagePrimitives:
    glyphs: list[Glyph]
    texts: list[TextLine]
    hlines: list[HLine]
    vlines: list[VLine]
    shapes: list[Shape]
    unknown_music_fonts: list[str]   # polices sans table de correspondance utilisable


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
                    symbol = SONATA_SYMBOLS.get(code) if role == "symbols" else None
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


def _polygons(items: list) -> Iterator[pymupdf.Rect]:
    """Boîtes des polygones d'un tracé rempli (les segments qui se suivent forment un polygone)."""
    points: list[pymupdf.Point] = []
    last_end: pymupdf.Point | None = None

    def box() -> pymupdf.Rect:
        return pymupdf.Rect(min(p.x for p in points), min(p.y for p in points),
                            max(p.x for p in points), max(p.y for p in points))

    for item in items:
        if item[0] == "re":
            yield pymupdf.Rect(item[1])
            continue
        if item[0] == "qu":
            yield item[1].rect
            continue
        start = item[1]
        if points and last_end is not None and abs(start.x - last_end.x) + abs(start.y - last_end.y) > 0.01:
            yield box()
            points = []
        points.extend(p for p in item[1:] if isinstance(p, pymupdf.Point))
        last_end = item[-1]
    if points:
        yield box()


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


def extract_lines(page: pymupdf.Page) -> tuple[list[HLine], list[VLine], list[Shape]]:
    """Range tous les tracés de la page en traits horizontaux, verticaux et formes épaisses.

    Page enregistrée tournée (ex. conducteur à l'italienne, rotation 270°) : PyMuPDF donne
    les tracés dans le repère d'origine, non tourné, où les portées sont verticales.
    On les ramène dans le repère de la page affichée (voir aussi extract_glyphs_and_texts).
    """
    hlines: list[HLine] = []
    vlines: list[VLine] = []
    shapes: list[Shape] = []
    matrix = page.rotation_matrix if page.rotation else None
    for drawing in page.get_drawings():
        filled = "f" in (drawing.get("type") or "")
        thickness = drawing.get("width") or 0.0
        if matrix is not None:
            drawing = {**drawing, "items": _rotated_items(drawing["items"], matrix)}
        if filled:
            for rect in _polygons(drawing["items"]):
                _classify_rect(rect, hlines, vlines, shapes)
            continue
        for item in drawing["items"]:
            if item[0] == "l":
                p, q = item[1], item[2]
                if thickness > MAX_LINE_THICKNESS:
                    # Trait épais (barre de pause multiple, barre finale) : forme épaisse.
                    half = thickness / 2
                    shapes.append(Shape(pymupdf.Rect(min(p.x, q.x) - half, min(p.y, q.y) - half,
                                                     max(p.x, q.x) + half, max(p.y, q.y) + half)))
                elif abs(p.y - q.y) < 0.05 and abs(q.x - p.x) > 0:
                    hlines.append(HLine((p.y + q.y) / 2, min(p.x, q.x), max(p.x, q.x)))
                elif abs(p.x - q.x) < 0.05 and abs(q.y - p.y) > 0:
                    vlines.append(VLine((p.x + q.x) / 2, min(p.y, q.y), max(p.y, q.y), thickness))
            elif item[0] == "re":
                # Rectangle seulement tracé : il compte s'il est assez fin pour être un trait.
                rect = pymupdf.Rect(item[1])
                if min(rect.width, rect.height) <= MAX_LINE_THICKNESS:
                    _classify_rect(rect, hlines, vlines, shapes)
    return hlines, vlines, shapes


def extract_primitives(page: pymupdf.Page) -> PagePrimitives:
    glyphs, texts = extract_glyphs_and_texts(page)
    hlines, vlines, shapes = extract_lines(page)
    return PagePrimitives(glyphs, texts, hlines, vlines, shapes, _unreadable_music_fonts(page))
