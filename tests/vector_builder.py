"""Fabrication de pages « vectorielles » pour les tests, sans police de musique.

Les polices de musique sont protégées : on ne peut pas en mettre dans le dépôt. On
fabrique donc directement les éléments qu'aurait extraits primitives.py (caractères,
traits, textes), placés comme dans un vrai PDF gravé.
"""

import pymupdf

from recomuse.vector.glyphs import SONATA_SYMBOLS, TIME_DIGITS
from recomuse.vector.primitives import Glyph, HLine, PagePrimitives, Shape, TextLine, VLine

# Codes utiles (table Sonata).
TREBLE, BASS, PERCUSSION = 0x26, 0x3F, 0x8B
BLACK, HALF, WHOLE = 0xCF, 0xFA, 0x77
WHOLE_REST, HALF_REST, QUARTER_REST = 0xB7, 0xEE, 0xCE
SHARP, FLAT, NATURAL = 0x23, 0x62, 0x6E
COMMON_TIME, HBAR = 0x63, 0xF6


class PageBuilder:
    """Construit les éléments d'une page, portée par portée."""

    def __init__(self) -> None:
        self.glyphs: list[Glyph] = []
        self.texts: list[TextLine] = []
        self.hlines: list[HLine] = []
        self.vlines: list[VLine] = []
        self.shapes: list[Shape] = []
        self.unknown_fonts: list[str] = []
        self.staves: list[tuple[float, float, float, float]] = []  # (haut, x0, x1, interligne)

    # --- Portées et barres -----------------------------------------------------------

    def staff(self, top: float, x0: float = 50, x1: float = 550, interline: float = 5.0,
              pieces: int = 1, barlines: list[float] | None = None) -> int:
        """Ajoute une portée (lignes éventuellement coupées en `pieces` morceaux jointifs)
        et ses barres de mesure ; renvoie son numéro."""
        width = (x1 - x0) / pieces
        for line in range(5):
            y = top + line * interline
            for k in range(pieces):
                self.hlines.append(HLine(y, x0 + k * width, x0 + (k + 1) * width))
        for x in barlines if barlines is not None else [x1]:
            self.vlines.append(VLine(x, top, top + 4 * interline, 0.5))
        self.staves.append((top, x0, x1, interline))
        return len(self.staves) - 1

    def y(self, staff: int, position: float) -> float:
        """Hauteur (points) d'une position sur une portée (0 = ligne du bas)."""
        top, _, _, interline = self.staves[staff]
        return top + 4 * interline - position * interline / 2

    # --- Caractères --------------------------------------------------------------------

    def glyph(self, staff: int, code: int, x: float, position: float, size: float = 20.0,
              font: str = "Maestro") -> Glyph:
        glyph = Glyph(code=code, symbol=SONATA_SYMBOLS.get(code), digit=TIME_DIGITS.get(code),
                      x=x, y=self.y(staff, position), size=size, font=font)
        self.glyphs.append(glyph)
        return glyph

    def note(self, staff: int, x: float, position: int, code: int = BLACK, size: float = 20.0,
             stem: bool = True) -> None:
        """Tête de note et sa hampe (vers le haut, collée au bord droit de la tête)."""
        self.glyph(staff, code, x, position, size=size)
        if stem and code != WHOLE:
            interline = self.staves[staff][3]
            head_y = self.y(staff, position)
            self.vlines.append(VLine(x + 1.2 * interline, head_y - 3.5 * interline, head_y, 0.5))

    def time(self, staff: int, x: float, upper: str, lower: str,
             positions: tuple[float, float] = (6, 2)) -> None:
        """Indication de mesure (chiffres superposés)."""
        for k, digit in enumerate(upper):
            self.glyph(staff, 0x30 + int(digit), x + 4 * k, positions[0])
        for k, digit in enumerate(lower):
            self.glyph(staff, 0x30 + int(digit), x + 4 * k, positions[1])

    def key(self, staff: int, x: float, positions: list[int], code: int = SHARP) -> None:
        """Armure : un signe par position, espacés d'un interligne."""
        interline = self.staves[staff][3]
        for k, position in enumerate(positions):
            self.glyph(staff, code, x + k * interline, position)

    # --- Autres éléments ---------------------------------------------------------------

    def text(self, text: str, x0: float, y0: float, x1: float, y1: float, size: float = 10) -> None:
        self.texts.append(TextLine(text, x0, y0, x1, y1, size))

    def shape(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.shapes.append(Shape(pymupdf.Rect(x0, y0, x1, y1)))

    def build(self) -> PagePrimitives:
        return PagePrimitives(self.glyphs, self.texts, self.hlines, self.vlines, self.shapes,
                              self.unknown_fonts)


# Positions des dièses et des bémols de l'armure en clé de sol.
TREBLE_SHARPS = [8, 5, 9, 6, 3, 7, 4]   # fa5 do5 sol5 ré5 la4 mi5 si4
TREBLE_FLATS = [4, 7, 3, 6, 2, 5, 1]    # si4 mi5 la4 ré5 sol4 do5 fa4
