"""Signes d'expression : liaisons, articulations, nuances, soufflets et tempo.

Où ils vivent dans le modèle :
- sur la note (ou le silence) qu'ils concernent, dans sa valeur :
  « slur_start » / « slur_stop » (liaison d'expression qui commence ou finit sur la note ;
  la liaison de prolongation, elle, est « tie_start » / « tie_stop »),
  « articulations » (liste : staccato, accent...), « dynamic » (nuance écrite sous la
  note : « mf »...), « wedge_start » (soufflet qui commence : « crescendo » ou
  « diminuendo ») et « wedge_stop » ;
- le tempo, en tête de mesure comme une clé : symbole « tempo » (texte « Allegro »,
  pulsation « beat » en noires et nombre de pulsations par minute « per_minute »).

Les noms sont ceux de RECOmuse ; les correspondances avec MusicXML, MEI (rendu Verovio)
et MIDI sont ici, pour que tous les modules parlent des mêmes signes.
"""

import re
from dataclasses import dataclass
from fractions import Fraction

from recomuse.model.score import Part, Symbol

# Articulations connues, et leur nom MusicXML (élément de <articulations>, sauf fermata,
# dans <notations>, et stopped, dans <technical>).
ARTICULATIONS = {
    "staccato": "staccato",
    "staccatissimo": "staccatissimo",
    "accent": "accent",
    "marcato": "strong-accent",
    "tenuto": "tenuto",
    "fermata": "fermata",
    "stopped": "stopped",
}
MUSICXML_ARTICULATIONS = {xml: ours for ours, xml in ARTICULATIONS.items()}

# Nom MEI (attribut @artic de <artic>) ; le point d'orgue est un élément <fermata> à part.
MEI_ARTICULATIONS = {"staccato": "stacc", "staccatissimo": "stacciss", "accent": "acc",
                     "marcato": "marc", "tenuto": "ten", "stopped": "stop"}

# Nuances, de la plus douce à la plus forte, et leur force MIDI (vélocité 1 à 127).
DYNAMICS = {"ppp": 20, "pp": 33, "p": 49, "mp": 64, "mf": 80, "f": 96, "ff": 112, "fff": 124,
            "fp": 96, "sf": 110, "sfz": 115, "sffz": 120, "rfz": 110}
# Force par défaut, sans nuance écrite (mezzo-forte).
DEFAULT_VELOCITY = DYNAMICS["mf"]

WEDGES = ("crescendo", "diminuendo")

# Mots d'indication de tempo (début de mot, sans accents, en minuscules) : un texte
# au-dessus de la portée qui commence ainsi est un tempo, pas une indication de jeu.
_TEMPO_WORDS = re.compile(
    r"^(allegr|allegretto|andant|adagi|moderat|larg|lent|prest|vivac|maestos|grave|"
    r"tempo|a tempo|rit|rall|accel|slow|fast|march|swing|ballad|rubato|meno|piu|"
    r"bright|lively|rock|latin|valse|waltz|polka|majestic|moving|calm)", re.IGNORECASE)

# Figures de la pulsation d'un métronome (« ♩ = 96 ») : durée en noires.
BEAT_UNITS = {"whole": Fraction(4), "half": Fraction(2), "quarter": Fraction(1),
              "eighth": Fraction(1, 2), "16th": Fraction(1, 4)}


def is_tempo_text(text: str) -> bool:
    """Vrai si ce texte écrit au-dessus de la portée est une indication de tempo."""
    return bool(_TEMPO_WORDS.match(text.strip()))


def beat_duration(unit: str | None, dotted: bool = False) -> Fraction | None:
    """Durée en noires de la pulsation d'un métronome (« quarter », pointée ou non)."""
    duration = BEAT_UNITS.get(unit or "")
    if duration is None:
        return None
    return duration * Fraction(3, 2) if dotted else duration


def beat_unit(duration: Fraction) -> tuple[str, bool] | None:
    """L'inverse : figure (et pointée ou non) d'une pulsation de `duration` noires."""
    for unit, value in BEAT_UNITS.items():
        if value == duration:
            return unit, False
        if value * Fraction(3, 2) == duration:
            return unit, True
    return None


# Vitesse habituelle (noires par minute) des mots de tempo, quand il n'y a pas de métronome.
TEMPO_WORD_SPEEDS = (("larg", 50), ("lent", 56), ("adagi", 66), ("slow", 66), ("andant", 80),
                     ("moderat", 100), ("allegrett", 112), ("allegr", 132), ("vivac", 152),
                     ("prest", 176), ("march", 116), ("fast", 152))


def quarters_per_minute(tempo: dict, guess_from_text: bool = False) -> float | None:
    """Noires par minute d'un symbole tempo (pour le MIDI) : celle du métronome, sinon (si
    `guess_from_text`) celle habituelle du mot de tempo (« Andante » → 80), sinon None."""
    per_minute, beat = tempo.get("per_minute"), tempo.get("beat")
    if per_minute:
        return float(per_minute * Fraction(beat or "1"))
    text = (tempo.get("text") or "").strip().lower()
    if guess_from_text:
        for start, speed in TEMPO_WORD_SPEEDS:
            if text.startswith(start):
                return float(speed)
    return None


# --- Liaisons et soufflets : de quelle note à quelle note --------------------------------

# Soufflet dont la fin n'a pas été lue : il s'arrête au plus tard à la fin de la mesure qui
# suit celle où il commence (sinon il traverserait tout le morceau).
OPEN_WEDGE_MEASURES = 1


@dataclass
class Span:
    """Liaison d'expression ou soufflet, d'une note à une autre (de la même partie)."""

    kind: str              # « slur » ou « wedge »
    start: Symbol
    end: Symbol
    start_rank: int        # rang de la mesure où il commence
    end_rank: int
    form: str | None = None   # soufflet : « crescendo » ou « diminuendo »


def spans(part: Part) -> list[Span]:
    """Liaisons et soufflets d'une partie, voix par voix.

    Une liaison va de « slur_start » au « slur_stop » suivant (une liaison sans fin n'est
    pas gardée). Un soufflet va de « wedge_start » au « wedge_stop » suivant ; si sa fin n'a
    pas été lue, il s'arrête juste avant la nuance ou le soufflet suivant, et au plus tard
    à la fin de la mesure qui suit."""
    result: list[Span] = []
    slurs: dict[int, list[tuple[int, Symbol]]] = {}
    wedges: dict[int, tuple[int, Symbol, str]] = {}
    previous: dict[int, tuple[int, Symbol]] = {}

    def close_wedge(voice: int, rank: int, end: Symbol) -> None:
        start_rank, start, form = wedges.pop(voice)
        result.append(Span("wedge", start, end, start_rank, rank, form))

    for rank, measure in enumerate(part.measures):
        if any(s.kind == "multirest" for s in measure.attributes):
            # Pause de plusieurs mesures : rien ne s'y joue, un soufflet ouvert s'arrête avant.
            for voice in list(wedges):
                close_wedge(voice, *previous[voice])
            continue
        for event in measure.events:
            value = event.value
            voice = value.get("voice") or 1
            if voice in wedges and rank > wedges[voice][0] + OPEN_WEDGE_MEASURES:
                close_wedge(voice, *previous[voice])
            if value.get("slur_stop") and slurs.get(voice):
                start_rank, start = slurs[voice].pop()
                result.append(Span("slur", start, event, start_rank, rank))
            if voice in wedges and value.get("wedge_stop"):
                close_wedge(voice, rank, event)
            elif voice in wedges and (value.get("dynamic") or value.get("wedge_start")):
                close_wedge(voice, *previous.get(voice, (rank, event)))
            if value.get("slur_start"):
                slurs.setdefault(voice, []).append((rank, event))
            if value.get("wedge_start") in WEDGES:
                wedges[voice] = (rank, event, value["wedge_start"])
            if not value.get("chord"):
                previous[voice] = (rank, event)
    for voice in list(wedges):
        close_wedge(voice, *previous[voice])
    return sorted(result, key=lambda s: (s.start_rank, s.kind))
