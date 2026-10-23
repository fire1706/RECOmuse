"""Portées retrouvées dans l'image d'une page, pour contrôler ce qu'Audiveris a lu.

Le validateur ne fait pas confiance aux portées d'Audiveris : il les retrouve lui-même
dans l'image de la page (à 300 dpi, celle de l'import), puis recalcule par exemple la
hauteur d'une note d'après la position de sa tête entre les lignes.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from recomuse.importer import preprocess
from recomuse.importer.loading import read_gray

# Une rangée de pixels porte une ligne de portée si ses longs traits couvrent au moins
# 30 % de la plus longue ligne de la page (les systèmes en retrait et les codas sont plus courts).
LINE_ROW_RATIO = 0.3

# Régularité des 5 lignes d'une portée (part de l'interligne).
SPACING_TOLERANCE = 0.2


@dataclass(frozen=True)
class StaffGeometry:
    """Une portée de l'image : hauteurs de ses 5 lignes, de haut en bas, et son étendue."""

    line_ys: tuple[float, ...]
    x0: int
    x1: int

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
        """Position en demi-interlignes au-dessus de la ligne du bas (0 = ligne du bas)."""
        return (self.bottom - y) / (self.interline / 2)

    def y_of(self, position: float) -> float:
        return self.bottom - position * self.interline / 2

    def distance(self, x: float, y: float) -> float:
        """Distance verticale d'un point à la portée (infinie s'il est hors de son étendue)."""
        if not self.x0 - self.interline <= x <= self.x1 + self.interline:
            return float("inf")
        return max(self.top - y, y - self.bottom, 0.0)


def find_staves(gray: np.ndarray) -> list[StaffGeometry]:
    """Portées de 5 lignes d'une image de page en niveaux de gris."""
    lines = preprocess.long_horizontal_lines(gray)
    rows = lines.sum(axis=1)
    if rows.max(initial=0) == 0:
        return []
    marked = np.nonzero(rows >= LINE_ROW_RATIO * rows.max())[0]

    # Rangées voisines = une même ligne (une ligne fait plusieurs pixels d'épaisseur).
    centers: list[tuple[float, int, int]] = []
    group = [int(marked[0])]
    for row in list(marked[1:]) + [None]:
        if row is not None and row - group[-1] <= 1:
            group.append(int(row))
            continue
        columns = np.nonzero(lines[group[0]:group[-1] + 1].any(axis=0))[0]
        centers.append((float(np.mean(group)), int(columns.min()), int(columns.max())))
        if row is not None:
            group = [int(row)]

    staves = []
    i = 0
    while i + 4 < len(centers):
        five = centers[i:i + 5]
        gaps = [five[k + 1][0] - five[k][0] for k in range(4)]
        spacing = sum(gaps) / 4
        if spacing >= 4 and max(gaps) - min(gaps) <= SPACING_TOLERANCE * spacing:
            staves.append(StaffGeometry(tuple(c[0] for c in five),
                                        x0=min(c[1] for c in five), x1=max(c[2] for c in five)))
            i += 5
        else:
            i += 1
    return staves


class PageGeometries:
    """Portées des pages d'une partition, calculées une seule fois par page."""

    def __init__(self) -> None:
        self._cache: dict[str, list[StaffGeometry]] = {}
        self._images: dict[str, np.ndarray] = {}

    def image(self, path: str) -> np.ndarray:
        if path not in self._images:
            self._images[path] = read_gray(Path(path))
        return self._images[path]

    def staves(self, path: str) -> list[StaffGeometry]:
        if path not in self._cache:
            self._cache[path] = find_staves(self.image(path))
        return self._cache[path]

    def staff_at(self, path: str, x: float, y: float, max_interlines: float = 6.0):
        """Portée à laquelle appartient un point (None si aucune n'est assez proche)."""
        best = min(self.staves(path), key=lambda s: s.distance(x, y), default=None)
        if best is None or best.distance(x, y) > max_interlines * best.interline:
            return None
        return best
