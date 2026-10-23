"""Fabrication de modèles et d'images de pages pour les tests du validateur."""

from pathlib import Path

import numpy as np

from recomuse.importer.loading import write_png
from recomuse.model.score import Measure, PageInfo, Part, ScoreModel, Symbol

# Portée dessinée dans les images de test : interligne 20 pixels, ligne du haut à y = 200.
STAFF_TOP, INTERLINE = 200, 20
STAFF_X0, STAFF_X1 = 100, 1900


def staff_y(position: float) -> float:
    """Hauteur (pixels) d'une position sur la portée de test (0 = ligne du bas)."""
    return STAFF_TOP + 4 * INTERLINE - position * INTERLINE / 2


def page_image(path: Path, hbar: tuple[int, int] | None = None) -> Path:
    """Page blanche avec une portée ; `hbar` : barre de pause multiple entre ces abscisses,
    avec au-dessus de la portée une tache à la place du nombre (lu par une fausse lecture)."""
    image = np.full((1200, 2000), 255, np.uint8)
    for line in range(5):
        y = STAFF_TOP + line * INTERLINE
        image[y - 1:y + 2, STAFF_X0:STAFF_X1] = 0
    if hbar:
        middle = int(staff_y(4))
        image[middle - 7:middle + 8, hbar[0]:hbar[1]] = 0
        center = (hbar[0] + hbar[1]) // 2
        image[STAFF_TOP - 50:STAFF_TOP - 20, center - 10:center + 10] = 0
    write_png(path, image)
    return path


def note(ident: str, step: str, octave: int, duration: str = "1", *, position: float | None = None,
         x: float = 300, source: str = "audiveris", voice: int = 1, **value) -> Symbol:
    """Note ; `position` place sa tête sur la portée de test (boîte de 24 × 20 pixels)."""
    bbox = None
    if position is not None:
        y = staff_y(position)
        bbox = (x, y - 10, 24, 20)
    return Symbol(id=ident, kind="note", page=1, bbox=bbox, source=source,
                  value={"step": step, "octave": octave, "alter": 0, "duration": duration,
                         "dots": 0, "voice": voice, "chord": False, "grace": False, **value})


def rest(ident: str, duration: str = "1", full: bool = False, source: str = "audiveris") -> Symbol:
    return Symbol(id=ident, kind="rest", page=1, source=source,
                  value={"duration": duration, "dots": 0, "voice": 1, "full_measure": full})


def attribute(ident: str, kind: str, source: str = "audiveris", confidence: float = 1.0,
              **value) -> Symbol:
    return Symbol(id=ident, kind=kind, value=value, page=1, source=source,
                  confidence=confidence, bbox=None)


def measure(ident: str, events=(), attributes=(), expected: str | None = "4", **fields) -> Measure:
    return Measure(id=ident, number=0, page=1, attributes=list(attributes), events=list(events),
                   expected_duration=expected, **fields)


def model_of(measures: list[Measure], image: Path | None = None, name: str | None = None,
             source: str = "audiveris") -> ScoreModel:
    model = ScoreModel(parts=[Part(id="P1", name=name, measures=measures)],
                       pages=[PageInfo(1, str(image) if image else None, 2000, 1200, source)])
    model.renumber()
    return model


def treble(ident: str = "c", **fields) -> Symbol:
    return attribute(ident, "clef", sign="G", line=2, **fields)


def four_four(ident: str = "t") -> Symbol:
    return attribute(ident, "time", beats=4, beat_type=4)
