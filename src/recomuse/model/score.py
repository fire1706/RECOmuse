"""Modèle interne d'une partition reconnue.

Organisation (proche de MusicXML) :
    ScoreModel → Part (une par instrument / portée) → Measure → Symbol

Un SYMBOLE est tout ce que l'utilisateur peut avoir à corriger : une note, un silence,
une clé, une armure, une indication de mesure, une pause multiple. Chaque symbole garde :
- sa valeur (dictionnaire, selon son type : voir VALUE_FIELDS) ;
- sa position : numéro de page et boîte en pixels de l'image de la page à 300 dpi
  (celle préparée à l'import) ; l'extrait d'image se découpe à partir de là ;
- sa confiance (0 à 1) : 1 pour une lecture vectorielle exacte, la note d'Audiveris sinon ;
- ses alternatives (autres valeurs possibles) ;
- sa source : « vector », « audiveris », ou celle de sa dernière correction (« user »,
  « rule », « validator »).
L'historique de ses valeurs n'est pas recopié ici : il est dans le journal des corrections
(learning/journal.py), qui reste la seule référence.

Les durées sont des fractions de noire écrites en texte (« 1/2 » = croche) : le modèle
s'enregistre en JSON, qui ne connaît pas les fractions.
"""

from dataclasses import asdict, dataclass, field
from fractions import Fraction
from typing import Any, Literal

# Version du format du modèle (pour pouvoir le faire évoluer plus tard).
MODEL_VERSION = 1

SymbolKind = Literal["note", "rest", "clef", "key", "time", "multirest"]
# Qui a donné sa valeur actuelle au symbole : lecture vectorielle, Audiveris, l'utilisateur
# (question ou édition), une règle apprise, ou le validateur musical.
SymbolSource = Literal["vector", "audiveris", "user", "rule", "validator"]

# Champs de la valeur de chaque type de symbole (documentation et contrôle).
VALUE_FIELDS: dict[str, tuple[str, ...]] = {
    # step : C D E F G A B ; alter : -1 bémol, 0, +1 dièse ; duration : « 1/2 »...
    "note": ("step", "octave", "alter", "duration", "dots", "voice", "chord", "grace",
             "tie_start", "tie_stop", "tuplet", "head"),
    "rest": ("duration", "dots", "voice", "full_measure"),
    "clef": ("sign", "line", "octave_change"),   # sign : G, F, C, percussion ; line : 1 à 5
    "key": ("fifths",),                   # > 0 dièses, < 0 bémols
    "time": ("beats", "beat_type"),
    "multirest": ("count",),
}


@dataclass
class Symbol:
    """Un élément corrigeable de la partition."""

    id: str
    kind: SymbolKind
    value: dict[str, Any]
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None   # x, y, largeur, hauteur (pixels)
    confidence: float = 1.0
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    source: SymbolSource = "vector"

    @property
    def duration(self) -> Fraction | None:
        """Durée en noires (notes et silences), ou None."""
        text = self.value.get("duration")
        return Fraction(text) if text is not None else None


@dataclass
class Measure:
    """Une mesure d'une partie."""

    id: str
    number: int                                   # numéro dans la partie (à partir de 1)
    page: int | None = None
    system: int | None = None                     # rang du système dans la page
    bbox: tuple[float, float, float, float] | None = None
    printed_number: int | None = None
    # Clé, armure, chiffrage, pause multiple.
    attributes: list[Symbol] = field(default_factory=list)
    events: list[Symbol] = field(default_factory=list)       # notes et silences, dans l'ordre
    expected_duration: str | None = None          # d'après le chiffrage en vigueur (« 3 »)
    marks: list[str] = field(default_factory=list)  # lettres de répétition (A, B...)

    @property
    def length(self) -> int:
        """Nombre de mesures représentées (une pause multiple en vaut plusieurs)."""
        for symbol in self.attributes:
            if symbol.kind == "multirest":
                return symbol.value["count"] or 1
        return 1

    def symbols(self) -> list[Symbol]:
        return self.attributes + self.events

    def duration(self, voice: int = 1) -> Fraction | None:
        """Durée lue d'une voix (appoggiatures exclues), ou None si une valeur manque."""
        total = Fraction(0)
        for symbol in self.events:
            if symbol.value.get("voice", 1) != voice or symbol.value.get("chord") \
                    or symbol.value.get("grace"):
                continue
            if symbol.duration is None:
                return None
            total += symbol.duration
        return total


@dataclass
class Part:
    id: str
    name: str | None = None
    measures: list[Measure] = field(default_factory=list)


@dataclass
class PageInfo:
    """Une page de la partition d'origine."""

    number: int
    image_path: str | None          # image préparée à 300 dpi (import)
    width: int = 0
    height: int = 0
    source: str = "none"            # qui a lu cette page : « vector », « audiveris », ou
                                    # « none » (pas de musique : couverture, notice...)


@dataclass
class ScoreModel:
    """Partition reconnue, prête à être vérifiée, corrigée puis exportée."""

    title: str | None = None
    composers: list[str] = field(default_factory=list)
    instrument: str | None = None
    tempo: str | None = None
    source_path: str | None = None
    parts: list[Part] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    version: int = MODEL_VERSION

    # --- Recherche -----------------------------------------------------------------------

    def symbols(self):
        """Tous les symboles, partie par partie, mesure par mesure."""
        for part in self.parts:
            for measure in part.measures:
                yield from measure.symbols()

    def find(self, symbol_id: str) -> tuple[Part, Measure, Symbol]:
        """Retrouve un symbole par son identifiant. Lève KeyError s'il n'existe pas."""
        for part in self.parts:
            for measure in part.measures:
                for symbol in measure.symbols():
                    if symbol.id == symbol_id:
                        return part, measure, symbol
        raise KeyError(symbol_id)

    def page(self, number: int) -> PageInfo | None:
        return next((p for p in self.pages if p.number == number), None)

    def renumber(self) -> None:
        """Renumérote les mesures de chaque partie (une pause multiple compte pour plusieurs)."""
        for part in self.parts:
            number = 1
            for measure in part.measures:
                measure.number = number
                number += measure.length

    # --- Enregistrement (JSON) -------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScoreModel":
        def symbol(d: dict) -> Symbol:
            bbox = tuple(d["bbox"]) if d.get("bbox") is not None else None
            return Symbol(**{**d, "bbox": bbox})

        def measure(d: dict) -> Measure:
            bbox = tuple(d["bbox"]) if d.get("bbox") is not None else None
            return Measure(**{**d, "bbox": bbox,
                              "attributes": [symbol(s) for s in d["attributes"]],
                              "events": [symbol(s) for s in d["events"]]})

        return cls(**{
            **data,
            "parts": [Part(**{**p, "measures": [measure(m) for m in p["measures"]]})
                      for p in data["parts"]],
            "pages": [PageInfo(**p) for p in data["pages"]],
        })


def fraction_text(value: Fraction | None) -> str | None:
    """Fraction → texte pour le JSON : Fraction(3, 2) → « 3/2 », Fraction(2) → « 2 »."""
    return None if value is None else str(value)
