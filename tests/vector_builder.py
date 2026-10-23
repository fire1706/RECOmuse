"""Fabrication de pages « vectorielles » pour les tests, sans police de musique.

Les polices de musique sont protégées : on ne peut pas en mettre dans le dépôt. On
fabrique donc directement les éléments qu'aurait extraits primitives.py (caractères,
traits, textes), placés comme dans un vrai PDF gravé.
"""

import pymupdf

from recomuse.vector.glyphs import SONATA_SYMBOLS, TIME_DIGITS
from recomuse.vector.primitives import (
    Beam,
    Curve,
    Glyph,
    HLine,
    PagePrimitives,
    Shape,
    TextLine,
    VLine,
)

# Codes utiles (table Sonata).
TREBLE, BASS, PERCUSSION = 0x26, 0x3F, 0x8B
BLACK, HALF, WHOLE = 0xCF, 0xFA, 0x77
WHOLE_REST, HALF_REST, QUARTER_REST = 0xB7, 0xEE, 0xCE
SHARP, FLAT, NATURAL = 0x23, 0x62, 0x6E
COMMON_TIME, HBAR = 0x63, 0xF6
EIGHTH_REST, DOT = 0xE4, 0x2E
FLAG_8_UP, FLAG_16_UP = 0x6A, 0x72

# Largeur d'une tête noire, en interlignes (comme dans les polices du corpus).
HEAD_WIDTH = 1.2


class PageBuilder:
    """Construit les éléments d'une page, portée par portée."""

    def __init__(self) -> None:
        self.glyphs: list[Glyph] = []
        self.texts: list[TextLine] = []
        self.hlines: list[HLine] = []
        self.vlines: list[VLine] = []
        self.shapes: list[Shape] = []
        self.beams: list[Beam] = []
        self.curves: list[Curve] = []
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
             stem: str | None = "up", flags: int = 0) -> VLine | None:
        """Tête de note et sa hampe ; renvoie la hampe.

        Hampe vers le haut : collée au bord droit de la tête ; vers le bas : au bord gauche.
        `flags` : 1 crochet (croche) ou 2 (double croche), au bout de la hampe.
        """
        self.glyph(staff, code, x, position, size=size)
        if stem is None or code == WHOLE:
            return None
        interline = self.staves[staff][3]
        head_y = self.y(staff, position)
        if stem == "up":
            line = VLine(x + HEAD_WIDTH * interline, head_y - 3.5 * interline, head_y, 0.5)
            end = line.y0
        else:
            line = VLine(x, head_y, head_y + 3.5 * interline, 0.5)
            end = line.y1
        self.vlines.append(line)
        if flags:
            code = FLAG_8_UP if flags == 1 else FLAG_16_UP
            symbol = SONATA_SYMBOLS[code]
            self.glyphs.append(Glyph(code=code, symbol=symbol, digit=None, x=line.x, y=end,
                                     size=size, font="Maestro"))
        return line

    def beam(self, staff: int, first: VLine, last: VLine, count: int = 1,
             up: bool = True) -> None:
        """Ligature(s) entre les bouts libres de deux hampes (vers le haut par défaut)."""
        interline = self.staves[staff][3]
        y0, y1 = (first.y0, last.y0) if up else (first.y1, last.y1)
        direction = 1 if up else -1   # les ligatures suivantes se rapprochent des têtes
        for k in range(count):
            offset = direction * (0.25 + 0.75 * k) * interline
            self.beams.append(Beam(first.x, y0 + offset, last.x, y1 + offset, 0.5 * interline))

    def dot(self, staff: int, x: float, position: float) -> None:
        """Point (de prolongation, s'il est juste à droite d'une tête)."""
        self.glyph(staff, DOT, x, position)

    def tie(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Liaison (courbe un peu creusée) d'un point à un autre."""
        self.curves.append(Curve(x0, y0, x1, y1, top=min(y0, y1), bottom=max(y0, y1) + 2))

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
                              self.unknown_fonts, self.beams, self.curves)


# Positions des dièses et des bémols de l'armure en clé de sol.
TREBLE_SHARPS = [8, 5, 9, 6, 3, 7, 4]   # fa5 do5 sol5 ré5 la4 mi5 si4
TREBLE_FLATS = [4, 7, 3, 6, 2, 5, 1]    # si4 mi5 la4 ré5 sol4 do5 fa4
