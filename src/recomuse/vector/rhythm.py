"""Rythmes d'une page vectorielle : hampes, ligatures, crochets, points, nolets, liaisons.

Toutes les durées sont des fractions de NOIRE : 1 = noire, 1/2 = croche, 3/2 = noire
pointée, 4 = ronde. (Fraction garde les valeurs exactes : un triolet de croches vaut
exactement 1/3, sans arrondi.)

Valeur d'une note :
- tête de ronde → 4 ; tête de blanche → 2 ;
- tête noire (ou croix, barre oblique) → 1, divisée par 2 pour chaque ligature ou
  crochet attaché à sa hampe (croche 1/2, double croche 1/4...) ;
- chaque point ajoute la moitié de ce qui précède (noire pointée 3/2, doublement 7/4) ;
- un nolet (triolet...) multiplie par normal / écrit (triolet : 2/3).

Géométrie, mesurée sur le corpus (en interlignes, « il ») :
- le point d'ancrage d'une tête est son bord gauche, sur sa ligne ou son interligne ;
- hampe vers le haut : collée au bord DROIT de la tête (environ 1,2 il plus loin) ;
  hampe vers le bas : au bord GAUCHE (même abscisse que l'ancrage) ;
- les ligatures (environ 0,5 il d'épaisseur) partent de l'extrémité libre de la hampe,
  empilées vers la tête tous les 0,75 il environ.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from statistics import median

from recomuse.vector.primitives import Beam, Curve, Glyph, VLine

# Largeur d'une tête noire en interlignes, si elle ne peut pas être mesurée sur la page.
DEFAULT_HEAD_WIDTH = 1.18

# Une hampe mesure au moins 1,5 interligne.
MIN_STEM_LENGTH = 1.5

# Tolérances de rattachement (en interlignes).
STEM_X_TOLERANCE = 0.3       # écart horizontal entre la hampe et le bord de la tête
WIDE_HEAD_RATIO = 1.3        # tête de blanche jusqu'à 30 % plus large qu'une noire
STEM_Y_TOLERANCE = 0.6       # une tête est « sur » la hampe à cette distance près
BEAM_REACH = 2.8             # les ligatures s'empilent sur cette hauteur depuis le bout
BEAM_MIN_THICKNESS = 0.25    # plus fin : morceau de ligne de portée, pas une ligature
BEAM_MAX_THICKNESS = 0.9
FLAG_REACH = 1.6             # un crochet est à cette distance du bout de la hampe

# Durée des têtes sans hampe et des silences, en noires.
HEAD_VALUE = {"whole": Fraction(4), "breve": Fraction(8), "half": Fraction(2)}
REST_VALUE = {
    "whole": Fraction(4), "half": Fraction(2), "quarter": Fraction(1),
    "eighth": Fraction(1, 2), "16th": Fraction(1, 4), "32nd": Fraction(1, 8),
    "64th": Fraction(1, 16),
}

# Nombre de crochets de chaque caractère.
FLAG_COUNT = {"eighth_up": 1, "eighth_down": 1, "16th_up": 2, "16th_down": 2}

# Nolets : nombre écrit → nombre « normal » de notes de même valeur dans le même temps.
TUPLET_NORMAL = {2: 3, 3: 2, 5: 4, 6: 4, 7: 4, 9: 8}


@dataclass
class Stem:
    """Une hampe et les têtes qu'elle porte (plusieurs têtes = un accord)."""

    line: VLine
    direction: str                   # "up" ou "down"
    heads: list[Glyph] = field(default_factory=list)
    beams: list[Beam] = field(default_factory=list)
    flags: int = 0

    @property
    def free_end(self) -> float:
        """Hauteur du bout libre (celui où s'attachent ligatures et crochets)."""
        return self.line.y0 if self.direction == "up" else self.line.y1


def estimate_head_width(heads: list[Glyph], vlines: list[VLine], interline: float) -> float:
    """Largeur d'une tête noire (en interlignes), mesurée sur les hampes vers le haut."""
    offsets = []
    for head in heads:
        for line in vlines:
            dx = (line.x - head.x) / interline
            if 0.8 <= dx <= 1.8 and abs(line.y1 - head.y) <= STEM_Y_TOLERANCE * interline \
                    and line.y1 - line.y0 >= MIN_STEM_LENGTH * interline:
                offsets.append(dx)
    return median(offsets) if offsets else DEFAULT_HEAD_WIDTH


def find_stems(heads: list[Glyph], vlines: list[VLine], interline: float,
               head_width: float) -> dict[int, Stem]:
    """Rattache chaque tête à sa hampe. Renvoie {id(tête): hampe}.

    Une tête est sur une hampe si elle touche l'une de ses extrémités, ou se trouve le long
    de la hampe (autres notes d'un accord). Côté horizontal, la tête est à gauche de la
    hampe, ou à sa droite pour une seconde dans un accord (tête « décalée »).
    """
    il = interline
    candidates = [v for v in vlines if v.y1 - v.y0 >= MIN_STEM_LENGTH * il]
    by_line: dict[int, Stem] = {}
    result: dict[int, Stem] = {}
    for head in heads:
        if head.symbol is None or head.symbol.name in ("whole", "breve"):
            continue
        best: tuple[float, VLine] | None = None
        for line in candidates:
            dx = (line.x - head.x) / il
            # Bord gauche (hampe vers le bas) à bord droit (vers le haut), plus têtes décalées.
            # Les têtes de blanche sont un peu plus larges que les noires (police Jazz : 30 %).
            if not -STEM_X_TOLERANCE <= dx <= WIDE_HEAD_RATIO * head_width + STEM_X_TOLERANCE:
                continue
            if not line.y0 - STEM_Y_TOLERANCE * il <= head.y <= line.y1 + STEM_Y_TOLERANCE * il:
                continue
            # Préférence : la hampe dont une extrémité est la plus proche de la tête.
            score = min(abs(line.y0 - head.y), abs(line.y1 - head.y)) / il + 0.1 * abs(
                dx - (head_width if abs(line.y1 - head.y) < abs(line.y0 - head.y) else 0))
            if best is None or score < best[0]:
                best = (score, line)
        if best is None:
            continue
        line = best[1]
        stem = by_line.get(id(line))
        if stem is None:
            stem = Stem(line=line, direction="up")
            by_line[id(line)] = stem
        stem.heads.append(head)
        result[id(head)] = stem

    # Sens de chaque hampe : elle dépasse ses têtes du côté de son bout libre.
    for stem in by_line.values():
        top_head = min(h.y for h in stem.heads)
        bottom_head = max(h.y for h in stem.heads)
        above = top_head - stem.line.y0
        below = stem.line.y1 - bottom_head
        stem.direction = "up" if above >= below else "down"
    return result


def attach_beams_and_flags(stems: list[Stem], beams: list[Beam], flags: list[Glyph],
                           interline: float) -> None:
    """Compte les ligatures et les crochets au bout libre de chaque hampe."""
    il = interline
    usable = [b for b in beams
              if BEAM_MIN_THICKNESS * il <= b.thickness <= BEAM_MAX_THICKNESS * il]
    for stem in stems:
        x = stem.line.x
        end = stem.free_end
        toward_head = 1 if stem.direction == "up" else -1
        for beam in usable:
            if not beam.x0 - STEM_X_TOLERANCE * il <= x <= beam.x1 + STEM_X_TOLERANCE * il:
                continue
            offset = (beam.y_at(x) - end) * toward_head   # > 0 : vers la tête
            if -0.6 * il <= offset <= BEAM_REACH * il:
                stem.beams.append(beam)
        for flag in flags:
            if -0.6 * il <= flag.x - x <= 0.8 * il and abs(flag.y - end) <= FLAG_REACH * il:
                stem.flags = max(stem.flags, FLAG_COUNT.get(flag.symbol.name, 1))


def base_value(head: str, stem: Stem | None) -> Fraction:
    """Valeur écrite d'une note, sans les points ni les nolets."""
    if head in HEAD_VALUE:
        return HEAD_VALUE[head]
    if stem is None:
        return Fraction(1)   # tête noire ou barre oblique sans hampe : une noire
    divisions = max(len(stem.beams), stem.flags)
    return Fraction(1, 2 ** divisions)


def count_dots(x_right: float, ys: list[float], dots: list[Glyph], used: set[int],
               interline: float) -> int:
    """Points de prolongation à droite d'une note ou d'un silence (0, 1 ou 2).

    Le premier point est à moins de 1,6 interligne du bord droit, à la hauteur d'une des
    têtes (décalé d'un demi-interligne vers le haut pour une note sur une ligne) ;
    le second suit à moins de 0,9 interligne. Les points déjà comptés (`used`) sont ignorés.
    """
    il = interline
    # Dans un accord, chaque tête a son point, tous dans la même colonne : on compte les
    # COLONNES de points (une colonne = un point de prolongation).
    columns: list[float] = []
    reach_start, reach_end = x_right - 0.2 * il, x_right + 1.6 * il
    for dot in sorted(dots, key=lambda d: d.x):
        if id(dot) in used or not any(abs(dot.y - y) <= 0.75 * il for y in ys):
            continue
        if columns and abs(dot.x - columns[-1]) <= 0.3 * il:
            used.add(id(dot))                      # même colonne que le point précédent
            continue
        if not reach_start <= dot.x <= reach_end or len(columns) == 2:
            continue
        used.add(id(dot))
        columns.append(dot.x)
        reach_start, reach_end = dot.x + 0.3 * il, dot.x + 0.9 * il
    return len(columns)


def dotted(value: Fraction, dots: int) -> Fraction:
    """Valeur prolongée par `dots` points : noire pointée = 1 + 1/2."""
    return value * (2 - Fraction(1, 2 ** dots))


def find_ties(heads: list[Glyph], curves: list[Curve], interline: float, head_width: float,
              position_of) -> list[tuple[Glyph | None, Glyph | None]]:
    """Liaisons de prolongation : courbes qui relient deux têtes de même hauteur.

    Renvoie des paires (tête de départ, tête d'arrivée). Une liaison qui sort de la portée
    (fin de ligne) a une arrivée None ; celle qui entre en début de ligne, un départ None.
    Ce sont les têtes trouvées près des extrémités de la courbe ; une courbe qui relie deux
    hauteurs différentes est une liaison d'expression : ignorée.
    """
    il = interline
    ties = []
    for curve in curves:
        # Une liaison de prolongation est plate : moins de 1,5 interligne de flèche.
        if curve.bottom - curve.top > 1.5 * il or curve.x1 - curve.x0 < 0.8 * il:
            continue
        start = _head_near(heads, curve.x0, curve.y0, il, head_width, side="left")
        end = _head_near(heads, curve.x1, curve.y1, il, head_width, side="right")
        if start is not None and end is not None:
            if position_of(start) == position_of(end) and end.x > start.x:
                ties.append((start, end))
        elif start is not None or end is not None:
            ties.append((start, end))
    return ties


def _head_near(heads: list[Glyph], x: float, y: float, il: float, head_width: float,
               side: str) -> Glyph | None:
    """Tête dont le bord est près de l'extrémité (x, y) d'une liaison."""
    best = None
    for head in heads:
        if side == "left":     # la liaison part du côté droit de la tête
            dx = x - (head.x + head_width * il)
        else:                  # elle arrive du côté gauche de la tête
            dx = head.x - x
        if -1.0 * il <= dx <= 1.2 * il and abs(head.y - y) <= 1.3 * il:
            distance = abs(dx) + abs(head.y - y)
            if best is None or distance < best[0]:
                best = (distance, head)
    return best[1] if best else None
