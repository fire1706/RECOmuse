"""Table des instruments (fichier instruments.json, modifiable sans toucher au code).

- reconnaître l'instrument d'après le nom écrit sur la partie (« Solo Bb Cornet »,
  « Klarinette 1 in B »...) et sa version (trompette en si bémol ou en ut, euphonium en
  clé de sol ou de fa) d'après ce nom et la clé de la partie ;
- connaître son étendue écrite (validateur) et sa transposition (instruments/transpose.py).
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi_number(step: str, alter: int, octave: int) -> int:
    """Numéro MIDI d'une note (do4 = 60) : sert à comparer des hauteurs."""
    return 12 * (octave + 1) + STEPS[step] + alter


def parse_note(text: str) -> int:
    """« Bb3 » → numéro MIDI ; « F#3 » ; « C7 »."""
    match = re.fullmatch(r"([A-G])(#|b)?(-?\d)", text)
    if not match:
        raise ValueError(f"Note illisible dans la table des instruments : {text}")
    alter = {"#": 1, "b": -1}.get(match.group(2) or "", 0)
    return midi_number(match.group(1), alter, int(match.group(3)))


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z]+", plain))


# Seconde, tierce... : demi-tons de l'intervalle majeur ou juste, de l'unisson à la septième.
MAJOR_SEMITONES = (0, 2, 4, 5, 7, 9, 11)
PERFECT_NUMBERS = (1, 4, 5)   # unisson, quarte, quinte (et leurs redoublements)


@dataclass(frozen=True)
class Interval:
    """Un intervalle : nombre de degrés (do → ré = 1) et de demi-tons (do → ré = 2).
    Négatif vers le grave. « M2 » = seconde majeure, « -M9 » = neuvième majeure plus bas."""

    steps: int
    semitones: int

    @classmethod
    def parse(cls, text: str) -> "Interval":
        """« P1 », « M2 », « m3 », « -M9 », « P8 », « A4 », « d5 »."""
        match = re.fullmatch(r"(-?)([PMmAd])(\d+)", text)
        if not match:
            raise ValueError(f"Intervalle illisible : {text}")
        sign = -1 if match.group(1) else 1
        quality, number = match.group(2), int(match.group(3))
        degree = (number - 1) % 7
        octaves = (number - 1) // 7
        semitones = MAJOR_SEMITONES[degree] + 12 * octaves
        perfect = degree + 1 in PERFECT_NUMBERS
        if quality in "PM" and (quality == "P") != perfect:
            raise ValueError(f"Intervalle impossible : {text}")
        semitones += {"P": 0, "M": 0, "m": -1, "A": 1, "d": -2 if not perfect else -1}[quality]
        return cls(sign * (number - 1), sign * semitones)

    def __neg__(self) -> "Interval":
        return Interval(-self.steps, -self.semitones)

    def __add__(self, other: "Interval") -> "Interval":
        return Interval(self.steps + other.steps, self.semitones + other.semitones)

    def __sub__(self, other: "Interval") -> "Interval":
        return self + -other


@dataclass(frozen=True)
class Variant:
    """Une version d'un instrument : sa tonalité, la clé de sa partie, sa transposition
    (de la note écrite à la note entendue ; None pour les percussions)."""

    id: str
    key: str | None              # « Bb », « Eb », « F », « C », « A »
    clef: str                    # « G2 », « F4 », « C3 », « C4 », « perc »
    transpose: Interval | None

    @property
    def clef_sign(self) -> str:
        return "percussion" if self.clef == "perc" else self.clef[0]

    @property
    def clef_value(self) -> dict:
        """Valeur du symbole « clef » du modèle pour cette clé."""
        if self.clef == "perc":
            return {"sign": "percussion", "line": None, "octave_change": 0}
        return {"sign": self.clef[0], "line": int(self.clef[1]), "octave_change": 0}


@dataclass(frozen=True)
class Instrument:
    id: str
    names: tuple[str, ...]
    # Étendue écrite selon le signe de la clé (« G », « F », « C ») :
    # (note la plus grave, note la plus aiguë), en numéros MIDI.
    ranges: dict[str, tuple[int, int]] = field(default_factory=dict)
    label: dict[str, str] = field(default_factory=dict)       # nom affiché, par langue
    variants: tuple[Variant, ...] = ()
    midi_program: int = 1        # son General MIDI (1 = piano, 57 = trompette...)

    def variant(self, variant_id: str | None) -> Variant | None:
        return next((v for v in self.variants if v.id == variant_id), None)


# Tonalité écrite dans un nom de partie : « in B », « en si b », « in Es », « en fa ».
KEY_WORDS = {"b": "Bb", "bb": "Bb", "bes": "Bb", "sib": "Bb", "si": "Bb",
             "es": "Eb", "eb": "Eb", "mib": "Eb", "mi": "Eb", "e": "Eb",
             "f": "F", "fa": "F", "c": "C", "ut": "C", "do": "C", "a": "A", "la": "A"}
# Mots qui suffisent seuls, sans « in » ni « en » : « Bb Cornet », « Sib ».
KEY_ALONE = {"bb": "Bb", "sib": "Bb", "bes": "Bb", "eb": "Eb", "mib": "Eb"}


def key_in_name(text: str | None) -> str | None:
    """Tonalité de l'instrument écrite dans le nom de la partie, ou None."""
    words = _normalize(text or "").split()
    for k, word in enumerate(words[:-1]):
        if word in ("in", "en", "inn") and words[k + 1] in KEY_WORDS:
            return KEY_WORDS[words[k + 1]]
    return next((KEY_ALONE[w] for w in words if w in KEY_ALONE), None)


class InstrumentTable:
    def __init__(self, instruments: list[Instrument]) -> None:
        self.instruments = instruments

    def get(self, instrument_id: str | None) -> Instrument | None:
        return next((i for i in self.instruments if i.id == instrument_id), None)

    def detect(self, name: str | None,
               clef_sign: str | None = None) -> tuple[Instrument, Variant] | None:
        """Instrument et version d'une partie, d'après son nom et sa clé : « Trumpet in
        B♭ 2 » → trompette en si bémol ; « Euphonium » en clé de fa → euphonium en ut."""
        instrument = self.find(name)
        if instrument is None or not instrument.variants:
            return None
        key = key_in_name(name)
        candidates = list(instrument.variants)
        for keep in (lambda v: v.key == key, lambda v: v.clef_sign == clef_sign):
            narrowed = [v for v in candidates if keep(v)]
            candidates = narrowed or candidates
        return instrument, candidates[0]

    def find(self, text: str | None) -> Instrument | None:
        """Instrument d'après un nom de partie, ou None. Le nom doit apparaître comme mots
        entiers (« cor » ne reconnaît pas « cornet »)."""
        if not text:
            return None
        words = f" {_normalize(text)} "
        for instrument in self.instruments:
            if any(f" {name} " in words for name in instrument.names):
                return instrument
        return None


def load_table(path: Path | None = None) -> InstrumentTable:
    """Lit la table (par défaut celle livrée avec RECOmuse)."""
    if path is None:
        text = resources.files("recomuse.instruments").joinpath("instruments.json").read_text(
            encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    return InstrumentTable([
        Instrument(id=item["id"], names=tuple(item["names"]),
                   ranges={sign: (parse_note(low), parse_note(high))
                           for sign, (low, high) in item["ranges"].items()},
                   label=dict(item.get("label") or {}),
                   midi_program=int(item.get("midi", 1)),
                   variants=tuple(
                       Variant(id=v["id"], key=v.get("key"), clef=v["clef"],
                               transpose=Interval.parse(v["transpose"])
                               if v.get("transpose") else None)
                       for v in item.get("variants", [])))
        for item in data["instruments"]
    ])
