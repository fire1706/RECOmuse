"""Construction du modèle à partir de la lecture vectorielle (pages vectorielles des PDF).

Ce qui est lu dans le PDF est exact : confiance 1, sauf dans les mesures dont la durée
ne correspond pas au chiffrage (confiance 0,5 : il y a sans doute un symbole mal lu).
Les positions passent des points PDF aux pixels de l'image de la page à 300 dpi
(celle préparée à l'import), dans laquelle les extraits d'image seront découpés.
"""

from recomuse.model import marks
from recomuse.model.score import Measure, Symbol, fraction_text
from recomuse.vector import VectorScore
from recomuse.vector.reader import Note, Rest
from recomuse.vector.reader import StaffContent as VectorStaff

# Points PDF → pixels à 300 dpi.
POINTS_TO_PIXELS = 300 / 72

# Confiance des symboles d'une mesure de durée incorrecte.
DOUBTFUL_CONFIDENCE = 0.5

# Largeur d'une tête de note (en interlignes), pour sa boîte.
HEAD_WIDTH = 1.2

# Clé vectorielle (nom, position de son ancrage) → clé MusicXML (signe, ligne, octave).
CLEF_SIGNS = {"treble": "G", "treble_8vb": "G", "bass": "F", "c": "C", "percussion": "percussion"}


def _box(x: float, y: float, width: float, height: float) -> tuple[float, float, float, float]:
    """Boîte (x, y = coin haut gauche) en points → en pixels à 300 dpi."""
    s = POINTS_TO_PIXELS
    return (round(x * s, 1), round(y * s, 1), round(width * s, 1), round(height * s, 1))


def clef_value(name: str, position: int | None) -> dict:
    """Clé : sol 2e ligne → {"sign": "G", "line": 2}. La ligne vient de la position de
    l'ancrage (0 = ligne du bas, 2 = 2e ligne...)."""
    line = (position // 2 + 1) if position is not None else 2
    value = {"sign": CLEF_SIGNS[name], "line": line if name != "percussion" else None}
    if name == "treble_8vb":
        value["octave_change"] = -1
    return value


def build_part_measures(score: VectorScore, rank: int) -> list[Measure]:
    """Mesures d'une partie (rang de portée `rank`) lues dans les pages vectorielles."""
    measures: list[Measure] = []
    current = {"clef": None, "key": None, "time": None}
    for page in score.pages:
        for system_index, system in enumerate(page.systems):
            if rank >= len(system):
                continue
            content = system[rank]
            for index, source in enumerate(content.measures):
                ident = f"v{page.page_number}.{system_index}.{rank}.{index}"
                measures.append(_measure(ident, source, content, page.page_number, system_index,
                                         current, is_first=not measures))
    return measures


def _measure(ident: str, source, content: VectorStaff, page: int, system: int,
             current: dict, is_first: bool) -> Measure:
    staff = content.staff
    il = staff.interline
    measure = Measure(
        id=ident, number=0, page=page, system=system,
        bbox=_box(source.x0, staff.top - il, source.x1 - source.x0,
                  staff.bottom - staff.top + 2 * il),
        printed_number=source.printed_number,
        expected_duration=fraction_text(source.expected_duration),
        marks=list(source.marks),
    )
    # Mesure de durée incorrecte : un symbole y est sans doute mal lu. Une première mesure
    # plus courte est une levée : elle est normale.
    pickup = (is_first and source.duration is not None
              and source.expected_duration is not None
              and source.duration < source.expected_duration)
    confidence = DOUBTFUL_CONFIDENCE if source.duration_ok is False and not pickup else 1.0

    def attribute(kind: str, value: dict, k: int) -> None:
        measure.attributes.append(Symbol(
            id=f"{ident}.{kind}{k}", kind=kind, value=value, page=page,
            bbox=_box(source.x0, staff.top, 3 * il, staff.bottom - staff.top)))

    # Clé, armure, chiffrage : seulement quand ils changent (les rappels en début de ligne
    # ne sont pas des changements).
    if source.clef:
        value = clef_value(source.clef, source.clef_position)
        if value != current["clef"]:
            attribute("clef", value, 0)
            current["clef"] = value
    if source.key_fifths is not None and source.key_fifths != current["key"]:
        attribute("key", {"fifths": source.key_fifths}, 0)
        current["key"] = source.key_fifths
    if source.time_signature and source.time_signature != current["time"]:
        beats, beat_type = source.time_signature.split("/")
        attribute("time", {"beats": int(beats), "beat_type": int(beat_type)}, 0)
        current["time"] = source.time_signature
    if source.is_multirest:
        attribute("multirest", {"count": source.multirest}, 0)

    for k, event in enumerate(_musical_order(source)):
        if isinstance(event, Note):
            y = staff.bottom - event.position * il / 2
            measure.events.append(Symbol(
                id=f"{ident}.n{k}", kind="note", page=page, confidence=confidence,
                bbox=_box(event.x, y - il / 2, HEAD_WIDTH * il, il),
                value={
                    "step": event.step, "octave": event.octave, "alter": event.alter,
                    "duration": fraction_text(event.duration), "dots": event.dots,
                    "voice": event.voice, "chord": event.chord, "grace": event.grace,
                    "tie_start": event.tie_start, "tie_stop": event.tie_stop,
                    "tuplet": list(event.tuplet) if event.tuplet else None,
                    "head": event.head,
                }))
        elif isinstance(event, Rest):
            y = staff.bottom - event.position * il / 2
            measure.events.append(Symbol(
                id=f"{ident}.r{k}", kind="rest", page=page, confidence=confidence,
                bbox=_box(event.x, y - 1.5 * il, 1.2 * il, 3 * il),
                value={"duration": fraction_text(event.duration), "dots": event.dots,
                       "voice": event.voice, "full_measure": source.full_rest}))
    _attach_marks(measure, getattr(source, "placed_marks", []))
    return measure


def _attach_marks(measure: Measure, placed: list[tuple[float, str, str]]) -> None:
    """Nuances et articulations lues dans le PDF : chacune va à la note (ou au silence,
    pour une nuance) la plus proche horizontalement."""
    leaders = [e for e in measure.events if not e.value.get("chord") and e.bbox is not None]
    for x, kind, name in placed:
        if kind == "dynamic" and name in marks.DYNAMICS:
            targets = leaders
        elif kind == "articulation" and name in marks.ARTICULATIONS:
            targets = [e for e in leaders if e.kind == "note" or name == "fermata"]
        else:
            continue
        if not targets:
            continue
        target = min(targets, key=lambda e: abs(e.bbox[0] - x))
        if kind == "dynamic":
            target.value["dynamic"] = name
        elif name not in target.value.setdefault("articulations", []):
            target.value["articulations"].append(name)


def _musical_order(source) -> list:
    """Notes et silences dans l'ordre de lecture, chaque note d'accord juste après la
    première note de son accord (la plus proche, dans la même voix)."""
    leaders = source.events()
    following: dict[int, list] = {id(leader): [] for leader in leaders}
    for note in (n for n in source.notes if n.chord):
        same_voice = [e for e in leaders
                      if isinstance(e, Note) and e.voice == note.voice] or leaders
        leader = min(same_voice, key=lambda e: abs(e.x - note.x))
        following[id(leader)].append(note)
    ordered = []
    for leader in leaders:
        ordered.append(leader)
        ordered += following[id(leader)]
    return ordered
