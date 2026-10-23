"""Repérage des portées, des barres de mesure et des systèmes à partir des traits.

PORTÉE : 5 longs traits horizontaux également espacés, de même début et même fin.
Les logiciels coupent parfois chaque ligne en morceaux (un par mesure) : on recolle
les morceaux d'une même hauteur avant de chercher les groupes de 5.

BARRE DE MESURE : trait vertical qui couvre la portée de sa première à sa dernière ligne.
Une hampe peut avoir la même longueur ; mais une hampe touche une tête de note,
pas une barre de mesure.

SYSTÈME : portées jouées ensemble (conducteur), reliées par leurs barres de mesure.
Dans une partie séparée, chaque portée forme son propre système.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from recomuse.vector.primitives import Glyph, HLine, Shape, VLine

# Longueur minimale d'une ligne de portée (points) : écarte les lignes supplémentaires.
MIN_STAFF_LINE_LENGTH = 40.0

# Deux morceaux d'une même ligne sont recollés s'ils sont séparés de moins de 2 points.
MAX_LINE_GAP = 2.0

# Deux traits sont à la même hauteur s'ils diffèrent de moins de 0,3 point.
SAME_ROW = 0.3

# Interligne acceptable, en points (de 1 point pour un conducteur minuscule à 20 points).
MIN_INTERLINE, MAX_INTERLINE = 1.0, 20.0

# Tolérance sur la régularité des 5 lignes (part de l'interligne).
SPACING_TOLERANCE = 0.15

# Tolérance pour qu'une barre de mesure « couvre » la portée (part de l'interligne).
BARLINE_TOLERANCE = 0.3

# Barres plus proches que cette distance (en interlignes) : une seule frontière
# (double barre, barre de reprise).
SAME_BARLINE = 1.0

# Une hampe est collée à une tête de note : le point d'ancrage d'une tête est son bord
# gauche, et la hampe part de ce bord (hampe vers le bas) ou du bord droit (vers le haut),
# environ 1,2 interligne plus loin. Bornes en interlignes, mesurées depuis l'ancrage.
STEM_X_RANGE = (-0.3, 1.6)
# ... et l'une des extrémités de la hampe est à la hauteur de la tête (en interlignes).
STEM_END_TO_HEAD = 0.75


@dataclass
class Staff:
    """Une portée de 5 lignes."""

    line_ys: list[float]          # hauteurs des 5 lignes, de haut en bas
    x0: float                     # début des lignes
    x1: float                     # fin des lignes
    barlines: list[float] = field(default_factory=list)   # abscisses des frontières de mesure

    @property
    def top(self) -> float:
        return self.line_ys[0]

    @property
    def bottom(self) -> float:
        return self.line_ys[-1]

    @property
    def interline(self) -> float:
        return (self.bottom - self.top) / 4

    def position(self, y: float) -> float:
        """Position verticale en demi-interlignes au-dessus de la ligne du bas.

        0 = ligne du bas (1re ligne), 1 = premier interligne, 8 = ligne du haut,
        -1 = juste sous la portée, 10 = 1re ligne supplémentaire au-dessus...
        """
        return (self.bottom - y) / (self.interline / 2)

    def vertical_distance(self, y: float) -> float:
        """Distance (points) entre y et la portée ; 0 si y est entre la 1re et la 5e ligne."""
        return max(self.top - y, y - self.bottom, 0.0)


def merge_rows(hlines: list[HLine]) -> list[HLine]:
    """Recolle les morceaux de traits horizontaux d'une même hauteur."""
    # Rangées : traits triés par hauteur, regroupés de proche en proche (un découpage en
    # « cases » fixes séparerait deux morceaux à 0,1 point d'écart tombés de part et
    # d'autre d'une limite).
    rows: list[list[HLine]] = []
    for line in sorted(hlines, key=lambda l: l.y):
        if rows and line.y - rows[-1][-1].y <= SAME_ROW:
            rows[-1].append(line)
        else:
            rows.append([line])

    merged = []
    for row in rows:
        pieces = sorted(row, key=lambda l: l.x0)
        y = sum(p.y for p in pieces) / len(pieces)
        start, end = pieces[0].x0, pieces[0].x1
        for piece in pieces[1:]:
            if piece.x0 <= end + MAX_LINE_GAP:
                end = max(end, piece.x1)
            else:
                merged.append(HLine(y, start, end))
                start, end = piece.x0, piece.x1
        merged.append(HLine(y, start, end))
    return merged


def find_staves(hlines: list[HLine]) -> list[Staff]:
    """Cherche les groupes de 5 lignes longues, régulièrement espacées."""
    long_lines = sorted((l for l in merge_rows(hlines) if l.x1 - l.x0 >= MIN_STAFF_LINE_LENGTH),
                        key=lambda l: (l.y, l.x0))
    # Traits doublés (contour d'une ligne épaisse) : on n'en garde qu'un.
    unique: list[HLine] = []
    for line in long_lines:
        previous = unique[-1] if unique else None
        if (previous and abs(line.y - previous.y) < 2 * SAME_ROW
                and line.x0 < previous.x1 and previous.x0 < line.x1):
            continue
        unique.append(line)

    staves = []
    # Recherche par fenêtre glissante, parmi les lignes qui ont même début et même fin
    # (deux portées de longueurs différentes ne se mélangent pas).
    for lines in _group_by_extent(unique):
        i = 0
        while i + 4 < len(lines):
            group = lines[i:i + 5]
            gaps = [group[k + 1].y - group[k].y for k in range(4)]
            spacing = sum(gaps) / 4
            if (MIN_INTERLINE <= spacing <= MAX_INTERLINE
                    and max(gaps) - min(gaps) <= SPACING_TOLERANCE * spacing):
                staves.append(Staff(line_ys=[l.y for l in group],
                                    x0=min(l.x0 for l in group), x1=max(l.x1 for l in group)))
                i += 5
            else:
                i += 1
    return sorted(staves, key=lambda s: (s.top, s.x0))


def _group_by_extent(lines: list[HLine]) -> list[list[HLine]]:
    """Regroupe les lignes dont le début et la fin coïncident (à 5 points près)."""
    groups: list[list[HLine]] = []
    for line in lines:
        for group in groups:
            ref = group[0]
            if abs(line.x0 - ref.x0) <= 5 and abs(line.x1 - ref.x1) <= 5:
                group.append(line)
                break
        else:
            groups.append([line])
    return [sorted(g, key=lambda l: l.y) for g in groups]


def _covers(line_y0: float, line_y1: float, staff: Staff) -> bool:
    tolerance = BARLINE_TOLERANCE * staff.interline
    return line_y0 <= staff.top + tolerance and line_y1 >= staff.bottom - tolerance


def find_barlines(staves: list[Staff], vlines: list[VLine], shapes: list[Shape],
                  noteheads: list[Glyph]) -> list[tuple[float, float, float]]:
    """Repère les barres de mesure de chaque portée et remplit Staff.barlines.

    Renvoie aussi la liste des barres (x, haut, bas), qui sert à former les systèmes.
    """
    candidates = [(v.x, v.y0, v.y1) for v in vlines]
    # Barres épaisses (barre finale, reprise) : formes pleines verticales.
    candidates += [((s.rect.x0 + s.rect.x1) / 2, s.rect.y0, s.rect.y1) for s in shapes
                   if s.rect.height > 3 * s.rect.width]

    found = []
    for x, y0, y1 in candidates:
        covered = [s for s in staves
                   if _covers(y0, y1, s) and s.x0 - s.interline <= x <= s.x1 + s.interline]
        if not covered:
            continue
        if _is_stem(x, y0, y1, noteheads, covered[0].interline):
            continue
        found.append((x, y0, y1))
        for staff in covered:
            staff.barlines.append(x)

    for staff in staves:
        staff.barlines = _merge_close(sorted(staff.barlines), SAME_BARLINE * staff.interline)
    return found


def _is_stem(x: float, y0: float, y1: float, noteheads: list[Glyph], interline: float) -> bool:
    """Vrai si le trait vertical part d'une tête de note (c'est alors une hampe)."""
    low, high = STEM_X_RANGE
    return any(
        low * interline <= x - head.x <= high * interline
        and min(abs(head.y - y0), abs(head.y - y1)) <= STEM_END_TO_HEAD * interline
        for head in noteheads
    )


def _merge_close(values: list[float], distance: float) -> list[float]:
    """Fusionne les valeurs proches (double barre → une seule frontière, la plus à droite)."""
    merged: list[float] = []
    for value in values:
        if merged and value - merged[-1] <= distance:
            merged[-1] = value
        else:
            merged.append(value)
    return merged


def group_systems(staves: list[Staff], barlines: list[tuple[float, float, float]]) -> list[list[int]]:
    """Regroupe les portées en systèmes (indices dans `staves`), de haut en bas.

    Deux portées sont du même système si un trait vertical les couvre toutes les deux.
    """
    parent = list(range(len(staves)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for x, y0, y1 in barlines:
        covered = [i for i, s in enumerate(staves)
                   if _covers(y0, y1, s) and s.x0 - s.interline <= x <= s.x1 + s.interline]
        for i in covered[1:]:
            parent[root(i)] = root(covered[0])

    systems: dict[int, list[int]] = defaultdict(list)
    for i in range(len(staves)):
        systems[root(i)].append(i)
    return reading_order(list(systems.values()), staves)


def reading_order(systems: list[list[int]], staves: list[Staff]) -> list[list[int]]:
    """Ordre de lecture des systèmes : colonne par colonne (de gauche à droite), puis de
    haut en bas. Certains PDF mettent deux pages côte à côte sur une feuille à l'italienne :
    le système de droite peut commencer plus haut que celui de gauche, et vient pourtant après.
    """
    def extent(members: list[int]) -> tuple[float, float]:
        return min(staves[i].x0 for i in members), max(staves[i].x1 for i in members)

    columns: list[list[list[int]]] = []
    for system in sorted(systems, key=lambda m: extent(m)[0]):
        x0, x1 = extent(system)
        for column in columns:
            c0, c1 = extent(column[0])
            if x0 < c1 and c0 < x1:  # les deux systèmes se chevauchent horizontalement
                column.append(system)
                break
        else:
            columns.append([system])
    return [system for column in columns
            for system in sorted(column, key=lambda m: staves[m[0]].top)]
