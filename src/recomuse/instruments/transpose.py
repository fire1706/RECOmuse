"""Transposition d'une partie : pour un autre instrument, ou d'un intervalle.

Pour un autre instrument (le cas de la fanfare : une partie d'euphonium en clé de fa à
lire au baryton en si bémol, clé de sol), on passe par les notes ENTENDUES :
    note entendue = note écrite + transposition de l'instrument d'origine
    nouvelle note écrite = note entendue − transposition du nouvel instrument
soit un seul intervalle, appliqué à toutes les notes et aux armures, et la clé du nouvel
instrument. Une octave de plus ou de moins peut être ajoutée (proposée quand la partie
sortirait de l'étendue du nouvel instrument).

Les notes gardent leur orthographe (do → ré, jamais do → si dièse). Si l'armure
obtenue est trop chargée (plus de 6 dièses ou bémols), l'enharmonie la plus simple est
prise (ré bémol majeur plutôt que do dièse majeur).

La transposition produit une NOUVELLE partition : celle d'origine reste telle quelle.
"""

from copy import deepcopy
from dataclasses import dataclass

from recomuse.instruments.table import Instrument, Interval, Variant, midi_number
from recomuse.model.score import ScoreModel, Symbol
from recomuse.vector.pitch import degree, from_degree

OCTAVE = Interval(7, 12)
# Armure de do majeur, sol, ré... : nombre de quintes depuis do pour chaque tonique.
TONIC_FIFTHS = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F": -1}
# Au-delà, on choisit l'enharmonie (une armure de 7 dièses se lit mal).
MAX_FIFTHS = 6
# Octaves essayées pour faire tenir la partie dans l'étendue du nouvel instrument.
OCTAVE_CHOICES = (0, -1, 1, -2, 2)


@dataclass(frozen=True)
class Request:
    """Une transposition demandée : l'intervalle, l'octave en plus, et pour un changement
    d'instrument le nouvel instrument (sa clé, son étendue, son nom)."""

    interval: Interval
    octave: int = 0
    instrument: Instrument | None = None
    variant: Variant | None = None


def for_instruments(source: Variant, target_instrument: Instrument, target: Variant,
                    octave: int = 0) -> Request:
    """Réécrire la partie d'un instrument (version `source`) pour un autre."""
    if source.transpose is None or target.transpose is None:
        raise ValueError("Une partie de percussions ne se transpose pas.")
    return Request(source.transpose - target.transpose, octave, target_instrument, target)


# --- Notes et armures ---------------------------------------------------------------------


def transpose_note(step: str, octave: int, alter: int,
                   interval: Interval) -> tuple[str, int, int]:
    """Une note transposée : (degré, octave, altération)."""
    new_step, new_octave = from_degree(degree(step, octave) + interval.steps)
    target = midi_number(step, alter, octave) + interval.semitones
    new_alter = target - midi_number(new_step, 0, new_octave)
    # Altération impossible à écrire (triple dièse...) : note voisine.
    while new_alter > 2 or new_alter < -2:
        shift = 1 if new_alter > 0 else -1
        new_step, new_octave = from_degree(degree(new_step, new_octave) + shift)
        new_alter = target - midi_number(new_step, 0, new_octave)
    return new_step, new_octave, new_alter


def tonic(fifths: int) -> tuple[str, int]:
    """Tonique majeure d'une armure : 0 → do, 2 → ré, -3 → mi bémol."""
    step, octave, alter = "C", 4, 0
    for _ in range(abs(fifths)):
        step, octave, alter = transpose_note(step, octave, alter,
                                             Interval(4, 7) if fifths > 0 else Interval(3, 5))
    return step, alter


def fifths_of(step: str, alter: int) -> int:
    """Armure de la tonalité majeure de cette tonique : mi bémol → -3."""
    return TONIC_FIFTHS[step] + 7 * alter


def transpose_fifths(fifths: int, interval: Interval) -> int:
    step, alter = tonic(fifths)
    new_step, _, new_alter = transpose_note(step, 4, alter, interval)
    return fifths_of(new_step, new_alter)


def simplest_spelling(interval: Interval, keys: list[int]) -> Interval:
    """L'intervalle tel quel, ou son enharmonie (même nombre de demi-tons, un degré de
    plus ou de moins) si elle donne des armures moins chargées."""
    def load(candidate: Interval) -> int:
        return max((abs(transpose_fifths(f, candidate)) for f in keys), default=0)
    if load(interval) <= MAX_FIFTHS:
        return interval
    candidates = [interval, Interval(interval.steps + 1, interval.semitones),
                  Interval(interval.steps - 1, interval.semitones)]
    return min(candidates, key=load)


# --- Partition ----------------------------------------------------------------------------


def transpose_model(model: ScoreModel, request: Request) -> tuple[ScoreModel, dict]:
    """Nouvelle partition transposée, et un compte rendu : armures obtenues, notes hors de
    l'étendue du nouvel instrument, octave conseillée."""
    keys = [s.value["fifths"] for s in model.symbols() if s.kind == "key"] or [0]
    base = simplest_spelling(request.interval, keys)
    result = deepcopy(model)
    total = base + Interval(OCTAVE.steps * request.octave, OCTAVE.semitones * request.octave)
    for part in result.parts:
        percussion = any(s.kind == "clef" and s.value.get("sign") == "percussion"
                         for m in part.measures for s in m.attributes)
        for measure in part.measures:
            for symbol in measure.attributes:
                if symbol.kind == "key" and not percussion:
                    _mark(symbol, {"fifths": transpose_fifths(symbol.value["fifths"], total)})
                elif symbol.kind == "clef" and request.variant is not None and not percussion:
                    _mark(symbol, request.variant.clef_value)
            for symbol in measure.events:
                value = symbol.value
                if percussion or symbol.kind != "note" or value.get("step") is None:
                    continue
                step, octave, alter = transpose_note(value["step"], value["octave"],
                                                     value.get("alter") or 0, total)
                _mark(symbol, {"step": step, "octave": octave, "alter": alter})
    if request.instrument is not None:
        result.instrument_id = request.instrument.id
        result.variant_id = request.variant.id if request.variant else None
    report = {
        "interval": {"steps": total.steps, "semitones": total.semitones},
        "keys": sorted({transpose_fifths(f, total) for f in keys}),
        "notes": sum(1 for s in result.symbols() if s.kind == "note"),
        "out_of_range": _out_of_range(result, request, 0),
        "suggested_octave": request.octave + _best_octave(result, request),
    }
    return result, report


def _mark(symbol: Symbol, value: dict) -> None:
    """Nouvelle valeur d'un symbole transposé : le validateur ne doit plus le comparer à
    sa position sur l'image (elle est celle de la partie d'origine)."""
    symbol.value = {**symbol.value, **value}
    symbol.source = "transposed"
    symbol.confidence = 1.0


def _out_of_range(model: ScoreModel, request: Request, shift: int) -> int:
    """Notes hors de l'étendue écrite du nouvel instrument (déplacées de `shift` octaves)."""
    if request.instrument is None or request.variant is None:
        return 0
    limits = request.instrument.ranges.get(request.variant.clef_sign)
    if limits is None:
        return 0
    low, high = limits
    count = 0
    for symbol in model.symbols():
        value = symbol.value
        if symbol.kind == "note" and value.get("step") is not None:
            number = midi_number(value["step"], value.get("alter") or 0, value["octave"])
            if not low <= number + 12 * shift <= high:
                count += 1
    return count


def _best_octave(model: ScoreModel, request: Request) -> int:
    """Octave à ajouter pour que le plus de notes tiennent dans l'étendue (0 si égal)."""
    return min(OCTAVE_CHOICES, key=lambda k: (_out_of_range(model, request, k),
                                              OCTAVE_CHOICES.index(k)))
