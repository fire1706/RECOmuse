"""Contrôle de la tessiture : une note hors de l'étendue de l'instrument est suspecte.

C'est presque toujours une erreur d'octave : si la note, déplacée d'une octave, rentre
dans l'étendue, on le propose. L'instrument est reconnu d'après le nom de la partie
(table des instruments).

Clé mal lue, trois cas :
- aucune clé lue au début de la partie (vu sur une partie de tuba : la clé de fa n'apparaît
  qu'à la 6e mesure, et les premières mesures s'affichent en clé de sol, la clé par
  défaut). On propose la clé lue plus loin (ou celle que l'étendue désigne). Audiveris a
  le plus souvent bien nommé les notes (il avait vu la clé) : on ne les renomme que si
  l'étendue montre qu'elles ont été nommées comme en clé de sol ;
- l'étendue : si la plupart des notes qui suivent une clé en sortent, alors qu'avec une
  autre clé de l'instrument elles y seraient presque toutes, c'est la clé qui est fausse ;
- un changement de clé en cours de partie (clé de fa depuis le début, puis clé de sol au
  3e système) : c'est rare dans une partie de fanfare, et Audiveris lit la clé de chaque
  système séparément (vu sur une partie de tuba). Les deux clés vont souvent à
  l'instrument (un tuba s'écrit en fa ou en sol) : on demande, sauf si l'étendue montre
  que la nouvelle clé est la bonne.
La correction proposée change la clé ET toutes les notes qu'elle gouverne (elles gardent
leur place sur la portée : leur nom change), jusqu'à la clé suivante.
"""

from recomuse.instruments.table import Instrument, InstrumentTable, load_table, midi_number
from recomuse.model.score import Part, ScoreModel, Symbol
from recomuse.validation.issues import Fix, Issue
from recomuse.validation.pitches import notes_with_clef
from recomuse.vector.pitch import clef_bottom_line, moved_by_clef

# Clés essayées pour chaque signe que l'instrument utilise (ligne de la clé), et leur nom
# (traduit par l'interface).
CLEF_CANDIDATES = {"G": [2], "F": [4], "C": [3, 4]}
CLEF_NAMES = {("G", 2): "treble", ("F", 4): "bass", ("C", 3): "alto", ("C", 4): "tenor"}
# Clé suspecte : avec elle, au plus la moitié des notes qu'elle gouverne sont dans
# l'étendue, et avec une autre clé de l'instrument au moins 90 %. Il faut assez de notes
# pour en juger.
CLEF_READ_MAX_SHARE = 0.5
CLEF_OTHER_MIN_SHARE = 0.9
CLEF_MIN_NOTES = 4


def _instrument(model: ScoreModel, part: Part, table: InstrumentTable) -> Instrument | None:
    name = part.name or (model.instrument if len(model.parts) == 1 else None)
    return table.get(model.instrument_id) or table.find(name)


def check_ranges(model: ScoreModel, table: InstrumentTable | None = None) -> list[Issue]:
    table = table or load_table()
    issues = []
    for part in model.parts:
        instrument = _instrument(model, part, table)
        if instrument is None:
            continue
        for measure, note, clef in notes_with_clef(part):
            value = note.value
            if clef is None or value.get("step") is None or value.get("octave") is None:
                continue
            limits = instrument.ranges.get(clef.value.get("sign"))
            if limits is None:
                continue
            low, high = limits
            number = midi_number(value["step"], value.get("alter") or 0, value["octave"])
            if low <= number <= high:
                continue
            shift = 1 if number < low else -1
            issue = Issue(
                code="note_out_of_range", part_id=part.id, measure_numbers=[measure.number],
                severity="warning", confidence=0.6, symbol_ids=[note.id],
                details={"instrument": instrument.id,
                         "note": f"{value['step']}{value['octave']}",
                         "direction": "low" if number < low else "high"},
            )
            if low <= number + 12 * shift <= high:
                issue.fixes.append(Fix(note.id, {"octave": value["octave"] + shift}))
            issues.append(issue)
    return issues


def check_clef_signs(model: ScoreModel, table: InstrumentTable | None = None) -> list[Issue]:
    """Clés mal lues : voir l'en-tête du module."""
    table = table or load_table()
    issues = []
    for part in model.parts:
        instrument = _instrument(model, part, table)
        established: dict | None = None    # dernière clé jugée juste
        sections = _clef_sections(part)
        for index, (clef, measure_number, notes) in enumerate(sections):
            if clef is None:
                later = sections[index + 1][0] if index + 1 < len(sections) else None
                issue = _missing_clef_issue(part, instrument, notes, later)
                if issue is not None:
                    issues.append(issue)
                continue
            issue = None
            if instrument is not None:
                issue = _clef_issue(part, instrument, clef, measure_number, notes)
            if issue is None and established is not None:
                issue = _clef_change_issue(part, instrument, clef, measure_number, notes,
                                           established)
            if issue is not None:
                issues.append(issue)
            else:
                established = clef.value
    return issues


def _clef_sections(part: Part):
    """(clé, numéro de sa mesure, [(note, armure en vigueur)]) pour chaque clé de la
    partie : les notes qu'elle gouverne, jusqu'à la clé suivante. Si la partie ne commence
    pas par une clé, la première section a pour clé None (notes nommées sans clé)."""
    sections: list[tuple[Symbol | None, int, list[tuple[Symbol, int]]]] = []
    if part.measures and not any(s.kind == "clef" for s in part.measures[0].attributes):
        sections.append((None, part.measures[0].number, []))
    fifths = 0
    for measure in part.measures:
        for symbol in measure.attributes:
            if symbol.kind == "clef":
                sections.append((symbol, measure.number, []))
            elif symbol.kind == "key":
                fifths = symbol.value.get("fifths") or 0
        if sections:
            sections[-1][2].extend((s, fifths) for s in measure.events
                                   if s.kind == "note" and s.value.get("step")
                                   and s.value.get("octave") is not None)
    return sections


def _share_in_range(values: list[dict], limits: tuple[int, int] | None) -> float:
    """Part des notes dans l'étendue (0 si l'instrument n'a pas d'étendue pour cette clé)."""
    if limits is None or not values:
        return 0.0
    low, high = limits
    inside = sum(low <= midi_number(v["step"], v.get("alter") or 0, v["octave"]) <= high
                 for v in values)
    return inside / len(values)


def _clef_issue(part: Part, instrument: Instrument, clef: Symbol, measure_number: int,
                notes: list[tuple[Symbol, int]]) -> Issue | None:
    """Doute sur une clé, si une autre clé de l'instrument explique bien mieux ses notes."""
    sign, line = clef.value.get("sign"), clef.value.get("line")
    if clef.source == "vector" or sign == "percussion" or len(notes) < CLEF_MIN_NOTES:
        return None
    read_share = _share_in_range([n.value for n, _ in notes], instrument.ranges.get(sign))
    if read_share > CLEF_READ_MAX_SHARE:
        return None
    best = None
    for other_sign, lines in CLEF_CANDIDATES.items():
        limits = instrument.ranges.get(other_sign)
        for other_line in lines if limits else []:
            if (other_sign, other_line) == (sign, line):
                continue
            candidate = {"sign": other_sign, "line": other_line, "octave_change": 0}
            shift = clef_bottom_line(candidate) - clef_bottom_line(clef.value)
            moved = [moved_by_clef(n.value, shift, fifths) for n, fifths in notes]
            share = _share_in_range(moved, limits)
            if best is None or share > best[0]:
                best = (share, candidate, moved)
    if best is None or best[0] < CLEF_OTHER_MIN_SHARE:
        return None
    share, candidate, _ = best
    return _clef_fix_issue(part, clef, measure_number, notes, candidate, "range",
                           round(0.5 + (share - read_share) / 2, 2),
                           {"instrument": instrument.id, "share_read": round(read_share, 2),
                            "share_proposed": round(share, 2)})


def _clef_change_issue(part: Part, instrument: Instrument | None, clef: Symbol,
                       measure_number: int, notes: list[tuple[Symbol, int]],
                       established: dict) -> Issue | None:
    """Doute sur une clé qui change en cours de partie (voir l'en-tête du module)."""
    sign, line = clef.value.get("sign"), clef.value.get("line")
    if (clef.source == "vector" or sign == "percussion" or not notes
            or (sign, line) == (established.get("sign"), established.get("line"))
            or (established.get("sign"), established.get("line")) not in CLEF_NAMES):
        return None
    candidate = {"sign": established["sign"], "line": established["line"],
                 "octave_change": established.get("octave_change") or 0}
    if instrument is not None:
        # L'étendue tranche si elle le peut : la nouvelle clé y va mieux → vrai changement.
        shift = clef_bottom_line(candidate) - clef_bottom_line(clef.value)
        moved = [moved_by_clef(n.value, shift, fifths) for n, fifths in notes]
        if (_share_in_range(moved, instrument.ranges.get(candidate["sign"]))
                < _share_in_range([n.value for n, _ in notes], instrument.ranges.get(sign))):
            return None
    return _clef_fix_issue(part, clef, measure_number, notes, candidate, "change", 0.6,
                           {"instrument": instrument.id if instrument else None})


# Clé que supposent des notes lues sans clé (celle que le MusicXML prend par défaut).
DEFAULT_CLEF = {"sign": "G", "line": 2, "octave_change": 0}


def _missing_clef_issue(part: Part, instrument: Instrument | None,
                        notes: list[tuple[Symbol, int]], later: Symbol | None) -> Issue | None:
    """Doute : la partie commence sans clé. On propose la clé lue plus loin, si elle n'est
    pas la clé de sol par défaut ; sinon, celle que l'étendue de l'instrument désigne."""
    if not notes:
        return None
    candidate = None
    rename = False
    later_name = (later.value.get("sign"), later.value.get("line")) if later else None
    if later_name in CLEF_NAMES and later_name != ("G", 2):
        candidate = {"sign": later.value["sign"], "line": later.value["line"],
                     "octave_change": later.value.get("octave_change") or 0}
    if candidate is None and instrument is not None:
        # Clé supposée (aucune n'a été lue) : jugée comme une clé lue par Audiveris.
        default = Symbol(id="", kind="clef", value=DEFAULT_CLEF, source="audiveris")
        found = _clef_issue(part, instrument, default, 0, notes)
        if found is not None:
            # L'étendue ne s'explique qu'en déplaçant les notes : elles ont été nommées
            # comme en clé de sol.
            candidate, rename = found.fixes[0].value, True
    if candidate is None:
        return None
    first = part.measures[0]
    shift = clef_bottom_line(candidate) - clef_bottom_line(DEFAULT_CLEF)
    issue = Issue(
        code="clef_sign_suspicious", part_id=part.id, measure_numbers=[first.number],
        severity="warning", confidence=0.7, symbol_ids=[n.id for n, _ in notes],
        details={"reason": "missing", "notes": len(notes), "read": "treble",
                 "proposed": CLEF_NAMES[(candidate["sign"], candidate["line"])],
                 "instrument": instrument.id if instrument else None, "rename": rename},
        action={"insert_clef": candidate, "measure_id": first.id})
    if rename:
        issue.fixes += [Fix(n.id, moved_by_clef(n.value, shift, fifths))
                        for n, fifths in notes]
    return issue


def _clef_fix_issue(part: Part, clef: Symbol, measure_number: int,
                    notes: list[tuple[Symbol, int]], candidate: dict, reason: str,
                    confidence: float, details: dict) -> Issue:
    """Le doute, et sa correction : la clé proposée, et le nouveau nom de chaque note."""
    sign, line = clef.value.get("sign"), clef.value.get("line")
    shift = clef_bottom_line(candidate) - clef_bottom_line(clef.value)
    issue = Issue(
        code="clef_sign_suspicious", part_id=part.id, measure_numbers=[measure_number],
        severity="warning", confidence=confidence,
        symbol_ids=[clef.id] + [n.id for n, _ in notes],
        details={"reason": reason, "notes": len(notes),
                 "read": CLEF_NAMES.get((sign, line), "other"),
                 "proposed": CLEF_NAMES[(candidate["sign"], candidate["line"])], **details})
    issue.fixes.append(Fix(clef.id, candidate))
    issue.fixes += [Fix(n.id, moved_by_clef(n.value, shift, fifths)) for n, fifths in notes]
    return issue
