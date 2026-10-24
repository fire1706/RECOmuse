"""Outils communs aux exports : durées écrites, altérations à imprimer, parties à exporter.

Les durées du modèle sont des fractions de noire (« 3/2 » = noire pointée) : la durée
réelle, points et nolets compris. Les exports ont besoin de la durée ÉCRITE (la figure :
blanche, croche...) et du nombre de points.
"""

from fractions import Fraction

from recomuse.model.score import Part, ScoreModel, Symbol
from recomuse.vector.pitch import key_alter

# Durée écrite (en noires) → nom de la figure en MusicXML.
NOTE_TYPES = {Fraction(8): "breve", Fraction(4): "whole", Fraction(2): "half",
              Fraction(1): "quarter", Fraction(1, 2): "eighth", Fraction(1, 4): "16th",
              Fraction(1, 8): "32nd", Fraction(1, 16): "64th", Fraction(1, 32): "128th"}
# Figure d'une note sans durée lue (petite note), d'après sa tête.
HEAD_TYPES = {"whole": Fraction(4), "half": Fraction(2)}


def written(symbol: Symbol) -> Fraction:
    """Durée écrite (sans point ni nolet), en noires."""
    duration = symbol.duration or HEAD_TYPES.get(symbol.value.get("head"), Fraction(1, 2))
    duration /= 2 - Fraction(1, 2 ** (symbol.value.get("dots") or 0))
    ratio = symbol.value.get("tuplet")
    if ratio:
        duration = duration * ratio[0] / ratio[1]
    return duration


def note_type(symbol: Symbol) -> str | None:
    """Nom MusicXML de la figure, ou None si la durée n'en est pas une (mal lue)."""
    return NOTE_TYPES.get(written(symbol))


class Accidentals:
    """Altérations à imprimer dans une mesure : une note n'a besoin d'un signe que s'il
    diffère de l'armure et des signes précédents de la mesure (sur la même note)."""

    def __init__(self, fifths: int) -> None:
        self.fifths = fifths
        self.current: dict[tuple[str, int], int] = {}

    def printed(self, step: str, octave: int, alter: int) -> int | None:
        """L'altération à imprimer (-1, 0, 1...) ou None s'il n'en faut pas."""
        expected = self.current.get((step, octave), key_alter(self.fifths, step))
        self.current[(step, octave)] = alter
        return alter if alter != expected else None


def exported_parts(model: ScoreModel) -> list[list[Part]]:
    """Parties à exporter, chacune avec ses portées : deux portées du même nom, avec le
    même nombre de mesures (piano), forment une seule partie ; une portée qui n'existe
    que sur certaines lignes est laissée de côté (elle ne s'aligne pas sur les autres)."""
    groups: list[list[Part]] = []
    for part in model.parts:
        if not part.measures:
            continue
        same = next((g for g in groups if g[0].name and g[0].name == part.name), None)
        if same is not None:
            if len(part.measures) == len(same[0].measures):
                same.append(part)
            continue
        groups.append([part])
    return groups

