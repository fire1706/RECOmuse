"""Table des instruments (fichier instruments.json, modifiable sans toucher au code).

Pour l'instant (tâche 6) : reconnaître l'instrument d'après le nom écrit sur la partie
(« Solo Bb Cornet », « Klarinette 1 in B »...) et connaître son étendue écrite.
La transposition et le changement de clé viendront à la tâche 10.
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


@dataclass(frozen=True)
class Instrument:
    id: str
    names: tuple[str, ...]
    # Étendue écrite selon le signe de la clé (« G », « F », « C ») :
    # (note la plus grave, note la plus aiguë), en numéros MIDI.
    ranges: dict[str, tuple[int, int]] = field(default_factory=dict)


class InstrumentTable:
    def __init__(self, instruments: list[Instrument]) -> None:
        self.instruments = instruments

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
                           for sign, (low, high) in item["ranges"].items()})
        for item in data["instruments"]
    ])
