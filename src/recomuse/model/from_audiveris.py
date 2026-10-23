"""Construction du modèle à partir d'Audiveris : la musique vient du MusicXML, la position
et la confiance de chaque symbole viennent du projet .omr (voir omr.py).

Appariement MusicXML ↔ .omr, mesure par mesure :
- les mesures du MusicXML se suivent dans l'ordre des systèmes indiqués par Audiveris
  (champ « source-sheet-N » du mouvement) ; celles du .omr aussi : on les associe une à une ;
- dans une mesure, chaque note du MusicXML a une abscisse « default-x » (en dixièmes
  d'interligne depuis le début de la mesure) : on prend l'accord du .omr le plus proche,
  en abscisse ET en hauteur (Audiveris peut voir deux « têtes » à la même abscisse, par
  exemple une vraie tête et un crochet pris pour une tête) ;
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
from recomuse.vector import pitch
from recomuse.vector.reader import REHEARSAL_MARK

# Pénalité (en pixels) par demi-interligne d'écart entre la hauteur attendue d'une note et
# celle de la tête du .omr, pour l'appariement.
PITCH_PENALTY = 40

# Confiance d'un symbole sans correspondant dans le .omr.
UNKNOWN_CONFIDENCE = 0.5

# Valeur écrite de chaque « type » MusicXML, en noires (pour les appoggiatures, sans durée).
TYPE_VALUE = {"breve": Fraction(8), "whole": Fraction(4), "half": Fraction(2),
              "quarter": Fraction(1), "eighth": Fraction(1, 2), "16th": Fraction(1, 4),
              "32nd": Fraction(1, 8), "64th": Fraction(1, 16)}

# Forme de la tête d'après le « type » MusicXML (toutes les autres valeurs : tête noire).
HEAD_OF_TYPE = {"whole": "whole", "half": "half", "breve": "breve"}

# Type de symbole du .omr pour chaque attribut.
ATTRIBUTE_KINDS = {"clef": ("clef",), "key": ("key",), "time": ("time-pair", "time-whole"),
                   "multirest": ("multiple-rest",)}


@dataclass
class _Geometry:
    """Correspondances de géométrie pour une mesure : feuille, échelle, mesure du .omr."""

    page: int
    scale: float                 # agrandissement de la feuille (diviser les pixels par lui)
    px_per_tenth: float          # pixels de la feuille par dixième MusicXML, dans cette mesure
    omr: OmrMeasure | None
    used: set[str] = field(default_factory=set)

    def box(self, bounds) -> tuple[float, float, float, float]:
        return tuple(round(v / self.scale, 1) for v in bounds)

    def measure_box(self) -> tuple[float, float, float, float] | None:
        """Colonne de la mesure, de la portée (ou de ses accords) en hauteur."""
        if self.omr is None:
            return None
        tops = [c.symbol.bounds[1] for c in self.omr.chords]
        bottoms = [c.symbol.bounds[1] + c.symbol.bounds[3] for c in self.omr.chords]
        if self.omr.staff_top is not None:
            tops.append(self.omr.staff_top)
            bottoms.append(self.omr.staff_bottom)
        if not tops:
            return None
        top, bottom = min(tops), max(bottoms)
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
            order = sorted(omr.systems, key=int) if omr else []
            for system_id in movement.sheet_systems[sheet_number]:
                systems = omr.systems.get(str(system_id), []) if omr else []
                rank = order.index(str(system_id)) if str(system_id) in order else None
                located.append((sheet_number, omr, systems, rank))
        for part_index, part in enumerate(root.findall("part")):
            while len(parts) <= part_index:
                parts.append([])
            omr_measures = _align(part, part_index, located)
            default_sheet = located[0][0] if located else 1
            parts[part_index] += _read_part(part, movement_index, part_index, omr_measures,
                                            default_sheet, book, page_width)
    return parts


def _system_breaks(part: ET.Element) -> list[list[ET.Element]]:
    """Mesures du MusicXML regroupées par système (marques <print new-system="yes"/>)."""
    systems: list[list[ET.Element]] = []
    for measure in part.findall("measure"):
        mark = measure.find("print")
        new = mark is not None and "yes" in (mark.get("new-system"), mark.get("new-page"))
        if new or not systems:
            systems.append([])
        systems[-1].append(measure)
    return systems


def _align(part: ET.Element, part_index: int, located: list) -> list:
    """Mesure du .omr (avec sa feuille) qui correspond à chaque mesure du MusicXML.

    Système par système : le k-ième système du MusicXML va avec le k-ième système du .omr.
    Dans un système, les deux ne comptent pas toujours le même nombre de mesures (le .omr
    garde par exemple la colonne d'un rappel d'armure en fin de ligne) : chaque mesure du
    MusicXML est placée d'après sa position relative dans le système (largeurs « width »),
    et associée à la colonne du .omr qui se trouve à la même position relative.
    """
    xml_systems = _system_breaks(part)
    result = []
    if len(xml_systems) != len(located):
        # Découpages incompatibles : association une à une, dans l'ordre.
        flat = [(sheet, omr, m, rank) for sheet, omr, systems, rank in located
                for m in (systems[part_index] if part_index < len(systems) else [])]
        for index, _ in enumerate(part.findall("measure")):
            result.append(flat[index] if index < len(flat) else (None, None, None, None))
        return result

    for xml_measures, (sheet, omr, systems, rank) in zip(xml_systems, located, strict=True):
        columns = systems[part_index] if part_index < len(systems) else []
        widths = [_float(m.get("width")) or 1.0 for m in xml_measures]
        total = sum(widths)
        if not columns:
            result += [(sheet, omr, None, rank)] * len(xml_measures)
            continue
        if len(columns) == len(xml_measures):
            # Même nombre de mesures des deux côtés : association une à une.
            result += [(sheet, omr, column, rank) for column in columns]
            continue
        left, right = columns[0].left, columns[-1].right
        done = 0.0
        for width in widths:
            center = left + (done + width / 2) / total * (right - left)
            done += width
            column = min(columns, key=lambda c: 0 if c.left <= center < c.right
                         else min(abs(c.left - center), abs(c.right - center)))
            result.append((sheet, omr, column, rank))
    return result


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
    clef: dict | None = None    # clé en vigueur (pour la hauteur attendue des têtes)
    for index, element in enumerate(part.findall("measure")):
        sheet_number, omr, omr_measure, system_rank = (
            omr_measures[index] if index < len(omr_measures) else (default_sheet, None, None, None))
        if sheet_number is None:
            sheet_number = default_sheet
        sheet_index = sheet_number - 1
        page = book.sheet_pages[sheet_index] if sheet_index < len(book.sheet_pages) else None
        scale = book.sheet_scales[sheet_index] if sheet_index < len(book.sheet_scales) else 1.0
        # Dixièmes MusicXML → pixels : d'après la largeur de CETTE mesure (attribut « width »
        # du MusicXML, colonne du .omr). Une échelle unique pour la page décale les notes.
        width = _float(element.get("width"))
        if omr_measure is not None and width:
            px_per_tenth = (omr_measure.right - omr_measure.left) / width
        else:
            px_per_tenth = (omr.width / page_width) if omr and page_width else 1.0
        geometry = _Geometry(page=page, scale=scale, px_per_tenth=px_per_tenth, omr=omr_measure)
        ident = f"a{movement}.{part_index}.{index}"
        measure = Measure(id=ident, number=0, page=page, system=system_rank,
                          bbox=geometry.measure_box())

        # Attributs : division de la noire, clé, armure, chiffrage, pause multiple.
        current_clef = clef
        for attributes in element.findall("attributes"):
            divisions = int(attributes.findtext("divisions") or divisions)
            for k, clef in enumerate(attributes.findall("clef")):
                value = {"sign": clef.findtext("sign"), "line": _int(clef.findtext("line"))}
                change = _int(clef.findtext("clef-octave-change"))
                if change:
                    value["octave_change"] = change
                _attribute(measure, geometry, "clef", value, k)
                current_clef = value
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
        measure.marks = _rehearsal_marks(element)

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
        clef = current_clef
        _locate_events(measure.events, geometry, clef)
        for symbol in measure.events:
            symbol.value.pop("_x", None)
        measures.append(measure)
    return measures


def _rehearsal_marks(element: ET.Element) -> list[str]:
    """Lettres de répétition d'une mesure du MusicXML (<rehearsal>, ou court texte au-dessus)."""
    marks = []
    for direction in element.findall("direction"):
        for item in direction.iter():
            text = (item.text or "").strip()
            rehearsal = item.tag == "rehearsal" and text
            short_above = (item.tag == "words" and direction.get("placement") != "below"
                           and REHEARSAL_MARK.match(text))
            if rehearsal or short_above:
                marks.append(text)
    return marks


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


def _staff_pitch(symbol: Symbol, clef: dict | None) -> float | None:
    """Hauteur attendue de la tête d'une note, à la façon d'Audiveris : 0 = ligne du milieu,
    positif vers le bas (en demi-interlignes)."""
    step, octave = symbol.value.get("step"), symbol.value.get("octave")
    names = {"G": "treble", "F": "bass", "C": "c"}
    if clef is None or step is None or octave is None or clef.get("sign") not in names:
        return None
    ref_step, ref_octave = pitch.CLEF_REFERENCE[names[clef["sign"]]]
    clef_position = ((clef.get("line") or 2) - 1) * 2
    written_octave = octave - (clef.get("octave_change") or 0)
    position = (pitch.degree(step, written_octave) - pitch.degree(ref_step, ref_octave)
                + clef_position)
    return 4 - position


def _match_cost(chord: OmrChord, x: float, wanted: float | None) -> float:
    """Coût d'appariement d'un accord du .omr : écart horizontal en pixels, plus une forte
    pénalité par demi-interligne d'écart de hauteur (une tête à la bonne hauteur l'emporte)."""
    distance = abs(chord.symbol.bounds[0] - x)
    pitches = [h.pitch for h in chord.heads if h.pitch is not None]
    if wanted is not None and pitches:
        distance += PITCH_PENALTY * min(abs(p - wanted) for p in pitches)
    return distance


def _locate_events(events: list[Symbol], geometry: _Geometry, clef: dict | None = None) -> None:
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
        wanted = None if wanted_rest else _staff_pitch(group[0], clef)
        chord = min(candidates, key=lambda c: _match_cost(c, x, wanted))
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
