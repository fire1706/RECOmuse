"""Construction du modèle à partir d'Audiveris : la musique vient du MusicXML, la position
et la confiance de chaque symbole viennent du projet .omr (voir omr.py).

Appariement MusicXML ↔ .omr, mesure par mesure :
- les mesures du MusicXML se suivent dans l'ordre des systèmes indiqués par Audiveris
  (champ « source-sheet-N » du mouvement) ; celles du .omr aussi : on les associe une à une ;
- dans une mesure, chaque note du MusicXML a une abscisse « default-x » (en dixièmes
  d'interligne depuis le début de la mesure) : on prend l'accord du .omr le plus proche ;
- dans un accord, les têtes sont associées aux notes de la plus grave à la plus aiguë.
Une note sans correspondant garde une confiance de 0,5 et la boîte de sa mesure.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction

from recomuse.model.omr import OmrChord, OmrMeasure, OmrSheet, read_sheet
from recomuse.model.score import Measure, Symbol, fraction_text
from recomuse.recognition.musicxml import read_root
from recomuse.recognition.pipeline import RecognitionResult

# Confiance d'un symbole sans correspondant dans le .omr.
UNKNOWN_CONFIDENCE = 0.5

# Valeur écrite de chaque « type » MusicXML, en noires (pour les appoggiatures, sans durée).
TYPE_VALUE = {"breve": Fraction(8), "whole": Fraction(4), "half": Fraction(2),
              "quarter": Fraction(1), "eighth": Fraction(1, 2), "16th": Fraction(1, 4),
              "32nd": Fraction(1, 8), "64th": Fraction(1, 16)}

# Forme de la tête d'après le « type » MusicXML (toutes les autres valeurs : tête noire).
HEAD_OF_TYPE = {"whole": "whole", "half": "half", "breve": "breve"}

# Type de symbole du .omr pour chaque attribut.
ATTRIBUTE_KINDS = {"clef": ("clef",), "key": ("key",), "time": ("time-pair", "time-whole")}


@dataclass
class _Geometry:
    """Correspondances de géométrie pour une mesure : feuille, échelle, mesure du .omr."""

    page: int
    scale: float                 # agrandissement de la feuille (diviser les pixels par lui)
    px_per_tenth: float          # pixels de la feuille par dixième d'interligne MusicXML
    omr: OmrMeasure | None
    used: set[str] = field(default_factory=set)

    def box(self, bounds) -> tuple[float, float, float, float]:
        return tuple(round(v / self.scale, 1) for v in bounds)

    def measure_box(self) -> tuple[float, float, float, float] | None:
        if self.omr is None or not self.omr.chords:
            return None
        xs = [c.symbol.bounds for c in self.omr.chords]
        top = min(b[1] for b in xs)
        bottom = max(b[1] + b[3] for b in xs)
        return self.box((self.omr.left, top, self.omr.right - self.omr.left, bottom - top))


def build_parts(result: RecognitionResult) -> list[list[Measure]]:
    """Mesures de chaque partie (ordre des parties du MusicXML), tous mouvements confondus."""
    book = result.run.book
    omr_path = result.run.omr_path
    sheets: dict[int, OmrSheet | None] = {}

    def sheet(number: int) -> OmrSheet | None:
        if number not in sheets:
            sheets[number] = read_sheet(omr_path, number) if omr_path else None
        return sheets[number]

    parts: list[list[Measure]] = []
    for movement_index, movement in enumerate(result.movements):
        root = read_root(movement.path)
        page_width = _float(root.findtext("defaults/page-layout/page-width"))
        # Mesures du .omr, dans l'ordre des systèmes du mouvement : (n° de feuille, mesures).
        located = []
        for sheet_number in sorted(movement.sheet_systems):
            omr = sheet(sheet_number)
            for system_id in movement.sheet_systems[sheet_number]:
                systems = omr.systems.get(str(system_id), []) if omr else []
                located.append((sheet_number, omr, systems))
        for part_index, part in enumerate(root.findall("part")):
            while len(parts) <= part_index:
                parts.append([])
            omr_measures = []
            for sheet_number, omr, systems in located:
                part_measures = systems[part_index] if part_index < len(systems) else []
                for omr_measure in part_measures or [None]:
                    omr_measures.append((sheet_number, omr, omr_measure))
            default_sheet = located[0][0] if located else 1
            parts[part_index] += _read_part(part, movement_index, part_index, omr_measures,
                                            default_sheet, book, page_width)
    return parts


def _float(text: str | None) -> float | None:
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _read_part(part: ET.Element, movement: int, part_index: int, omr_measures: list,
               default_sheet: int, book, page_width: float | None) -> list[Measure]:
    measures = []
    divisions = 1
    expected: Fraction | None = None
    for index, element in enumerate(part.findall("measure")):
        sheet_number, omr, omr_measure = (omr_measures[index] if index < len(omr_measures)
                                          else (default_sheet, None, None))
        sheet_index = sheet_number - 1
        page = book.sheet_pages[sheet_index] if sheet_index < len(book.sheet_pages) else None
        scale = book.sheet_scales[sheet_index] if sheet_index < len(book.sheet_scales) else 1.0
        px_per_tenth = (omr.width / page_width) if omr and page_width else 1.0
        geometry = _Geometry(page=page, scale=scale, px_per_tenth=px_per_tenth, omr=omr_measure)
        ident = f"a{movement}.{part_index}.{index}"
        measure = Measure(id=ident, number=0, page=page, bbox=geometry.measure_box())

        # Attributs : division de la noire, clé, armure, chiffrage, pause multiple.
        for attributes in element.findall("attributes"):
            divisions = int(attributes.findtext("divisions") or divisions)
            for k, clef in enumerate(attributes.findall("clef")):
                value = {"sign": clef.findtext("sign"), "line": _int(clef.findtext("line"))}
                change = _int(clef.findtext("clef-octave-change"))
                if change:
                    value["octave_change"] = change
                _attribute(measure, geometry, "clef", value, k)
            for k, key in enumerate(attributes.findall("key")):
                fifths = _int(key.findtext("fifths")) or 0
                _attribute(measure, geometry, "key", {"fifths": fifths}, k)
            for k, time in enumerate(attributes.findall("time")):
                beats, beat_type = _int(time.findtext("beats")), _int(time.findtext("beat-type"))
                if beats and beat_type:
                    _attribute(measure, geometry, "time",
                               {"beats": beats, "beat_type": beat_type}, k)
                    expected = Fraction(beats * 4, beat_type)
            multiple = attributes.findtext("measure-style/multiple-rest")
            if multiple:
                _attribute(measure, geometry, "multirest", {"count": int(multiple)}, 0)
        if omr_measure is not None and omr_measure.multirest_count and not any(
                s.kind == "multirest" for s in measure.attributes):
            _attribute(measure, geometry, "multirest", {"count": omr_measure.multirest_count}, 0)
        measure.expected_duration = fraction_text(expected)

        # Notes et silences.
        chord_leader: Symbol | None = None
        for k, note in enumerate(element.findall("note")):
            symbol = _note(note, f"{ident}.e{k}", divisions, geometry)
            if symbol.value.get("chord") and chord_leader is not None:
                # Même accord : même position horizontale que la première note.
                symbol.value["_x"] = chord_leader.value.get("_x")
            else:
                chord_leader = symbol
            measure.events.append(symbol)
        _locate_events(measure.events, geometry)
        for symbol in measure.events:
            symbol.value.pop("_x", None)
        measures.append(measure)
    return measures


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _attribute(measure: Measure, geometry: _Geometry, kind: str, value: dict, k: int) -> None:
    symbol = Symbol(id=f"{measure.id}.{kind}{k}", kind=kind, value=value, page=geometry.page,
                    source="audiveris", confidence=UNKNOWN_CONFIDENCE, bbox=measure.bbox)
    if geometry.omr is not None:
        match = next((s for s in geometry.omr.attributes
                      if s.kind in ATTRIBUTE_KINDS.get(kind, ())
                      and s.id not in geometry.used), None)
        if match is not None:
            geometry.used.add(match.id)
            symbol.bbox = geometry.box(match.bounds)
            symbol.confidence = match.grade
    measure.attributes.append(symbol)


def _note(note: ET.Element, ident: str, divisions: int, geometry: _Geometry) -> Symbol:
    """Une note ou un silence du MusicXML → symbole du modèle (sans position pour l'instant)."""
    rest = note.find("rest")
    grace = note.find("grace") is not None
    written_type = note.findtext("type")
    duration_text = note.findtext("duration")
    if duration_text is not None and not grace:
        duration = Fraction(int(duration_text), divisions)
    else:
        duration = TYPE_VALUE.get(written_type or "", None)
    dots = len(note.findall("dot"))
    voice = _int(note.findtext("voice")) or 1
    modification = note.find("time-modification")
    tuplet = None
    if modification is not None:
        tuplet = [_int(modification.findtext("actual-notes")),
                  _int(modification.findtext("normal-notes"))]
    default_x = _float(note.get("default-x"))
    x = None
    if geometry.omr is not None and default_x is not None:
        x = geometry.omr.left + default_x * geometry.px_per_tenth

    if rest is not None:
        value = {"duration": fraction_text(duration), "dots": dots, "voice": voice,
                 "full_measure": rest.get("measure") == "yes"}
        kind = "rest"
    else:
        ties = {t.get("type") for t in note.findall("tie")}
        value = {
            "step": note.findtext("pitch/step"), "octave": _int(note.findtext("pitch/octave")),
            "alter": _int(note.findtext("pitch/alter")) or 0,
            "duration": fraction_text(duration), "dots": dots, "voice": voice,
            "chord": note.find("chord") is not None, "grace": grace,
            "tie_start": "start" in ties, "tie_stop": "stop" in ties, "tuplet": tuplet,
            "head": HEAD_OF_TYPE.get(written_type or "", "black"),
        }
        kind = "note"
    value["_x"] = x   # position attendue, retirée après l'appariement
    return Symbol(id=ident, kind=kind, value=value, page=geometry.page, source="audiveris",
                  confidence=UNKNOWN_CONFIDENCE, bbox=None)


def _locate_events(events: list[Symbol], geometry: _Geometry) -> None:
    """Donne à chaque note ou silence la boîte et la confiance de son correspondant du .omr."""
    fallback = geometry.measure_box()
    if geometry.omr is None:
        for symbol in events:
            symbol.bbox = fallback
        return
    free: list[OmrChord] = list(geometry.omr.chords)

    # Les notes d'un même accord partagent une position : on les traite ensemble.
    groups: list[list[Symbol]] = []
    for symbol in events:
        if symbol.value.get("chord") and groups:
            groups[-1].append(symbol)
        else:
            groups.append([symbol])

    for group in groups:
        x = group[0].value.get("_x")
        wanted_rest = group[0].kind == "rest"
        candidates = [c for c in free if c.is_rest == wanted_rest]
        if x is None or not candidates:
            for symbol in group:
                symbol.bbox = fallback
            continue
        chord = min(candidates, key=lambda c: abs(c.symbol.bounds[0] - x))
        free.remove(chord)
        if wanted_rest or not chord.heads:
            for symbol in group:
                symbol.bbox = geometry.box(chord.symbol.bounds)
                symbol.confidence = chord.symbol.grade
            continue
        # Têtes de la plus grave (en bas, y grand) à la plus aiguë ; notes dans le même ordre.
        heads = sorted(chord.heads, key=lambda h: -h.bounds[1])
        notes = sorted(group, key=_pitch_rank)
        for symbol, head in zip(notes, heads, strict=False):
            symbol.bbox = geometry.box(head.bounds)
            symbol.confidence = head.grade
        for symbol in notes[len(heads):]:
            symbol.bbox = geometry.box(chord.symbol.bounds)
            symbol.confidence = chord.symbol.grade


def _pitch_rank(symbol: Symbol) -> int:
    """Rang de hauteur (pour trier les notes d'un accord de la plus grave à la plus aiguë)."""
    steps = "CDEFGAB"
    step = symbol.value.get("step")
    octave = symbol.value.get("octave")
    return (octave or 0) * 7 + (steps.index(step) if step in steps else 0)
