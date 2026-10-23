"""Lecture d'une page vectorielle : portées, mesures, clés, armures, chiffrages,
pauses multiples, notes (hauteur écrite exacte), silences et textes.

Tâche 4b-1 : la durée des notes (hampes, crochets, ligatures, points) n'est pas encore
interprétée ; ce sera la tâche 4b-2. Ce qui est lu ici sert déjà à contrôler Audiveris :
nombre de mesures, changements de chiffrage, pauses multiples, hauteurs et octaves.
"""

import re
from dataclasses import dataclass, field
from itertools import pairwise
from statistics import median

import pymupdf

from recomuse.vector import pitch
from recomuse.vector.primitives import (
    Glyph,
    PagePrimitives,
    Shape,
    TextLine,
    extract_primitives,
)
from recomuse.vector.staves import Staff, find_barlines, find_staves, group_systems

# Un symbole appartient à la portée la plus proche s'il en est à moins de 6 interlignes.
MAX_STAFF_DISTANCE = 6.0

# Une altération est celle d'une note si elle est juste à sa gauche (moins de 3,5 interlignes)
# et à la même hauteur.
ACCIDENTAL_REACH = 3.5

# Une tête plus petite que 85 % de la taille habituelle est une petite note (appoggiature,
# note de réplique).
SMALL_NOTE_RATIO = 0.85

# Écart maximal entre deux signes d'une armure, en interlignes.
KEY_SIGNATURE_GAP = 1.8

# Une altération à moins de 1,6 interligne d'une note de même hauteur est celle de la note.
NOTE_ACCIDENTAL_DISTANCE = 1.6

# Largeur minimale d'une mesure, en interlignes.
MIN_MEASURE_WIDTH = 2.0

# Écart toléré entre la position mesurée d'un symbole et une ligne / un interligne.
POSITION_TOLERANCE = 0.3

# Avertissements (codes traduits par l'interface).
#   no_staff_found           : aucune portée de 5 lignes
#   unreadable_music_font    : police de musique intégrée sans table de caractères
#   no_clef                  : portée sans clé lisible, clé de sol supposée
#   multirest_count_missing  : pause multiple dont le nombre n'a pas été trouvé
#   off_position             : symbole entre deux positions (à vérifier)
#   variable_staff_count     : systèmes de tailles différentes (conducteur à portées masquées)


@dataclass
class Note:
    """Une tête de note avec sa hauteur écrite."""

    x: float
    position: int                  # 0 = ligne du bas de la portée
    head: str                      # black, half, whole, breve, x, slash
    step: str | None = None        # None sur une portée de percussions
    octave: int | None = None
    alter: int = 0                 # -1 bémol, 0, +1 dièse (armure et altérations comprises)
    accidental: str | None = None  # altération écrite devant la note
    small: bool = False            # petite note (appoggiature, réplique)

    @property
    def name(self) -> str | None:
        if self.step is None or self.octave is None:
            return None
        return pitch.pitch_name(self.step, self.octave, self.alter)


@dataclass
class Rest:
    x: float
    value: str                     # whole, half, quarter, eighth, 16th...


@dataclass
class Measure:
    """Une mesure d'une portée."""

    x0: float
    x1: float
    notes: list[Note] = field(default_factory=list)
    rests: list[Rest] = field(default_factory=list)
    clef: str | None = None              # clé écrite dans la mesure (début de ligne ou changement)
    key_fifths: int | None = None        # armure écrite dans la mesure
    time_signature: str | None = None    # ex. « 3/4 », écrit dans la mesure
    multirest: int | None = None         # nombre de mesures d'une pause multiple
    is_multirest: bool = False
    measure_repeat: bool = False         # signe de répétition de la mesure précédente
    printed_number: int | None = None    # numéro de mesure imprimé
    symbols: list[str] = field(default_factory=list)  # nuances, articulations, coda...
    texts: list[str] = field(default_factory=list)

    @property
    def full_rest(self) -> bool:
        """Mesure entière de silence (une pause seule)."""
        return not self.notes and [r.value for r in self.rests] == ["whole"]

    @property
    def length(self) -> int:
        """Nombre de mesures réellement représentées (une pause multiple en vaut plusieurs)."""
        return self.multirest if self.is_multirest and self.multirest else 1


@dataclass
class StaffContent:
    staff: Staff
    measures: list[Measure]
    clef: str | None = None              # clé en vigueur au début de la portée
    clef_position: int | None = None


@dataclass
class VectorPage:
    page_number: int
    systems: list[list[StaffContent]]
    header_lines: list[TextLine]         # textes au-dessus de la première portée
    texts: list[TextLine]                # textes non rattachés à une mesure
    warnings: list[str] = field(default_factory=list)

    @property
    def interline(self) -> float | None:
        staves = [s.staff for system in self.systems for s in system]
        return median(s.interline for s in staves) if staves else None


def _rounded_position(staff: Staff, y: float) -> tuple[int, bool]:
    """Position entière la plus proche, et vrai si le symbole est bien centré dessus."""
    value = staff.position(y)
    nearest = round(value)
    return nearest, abs(value - nearest) <= POSITION_TOLERANCE


def _nearest_staff(staves: list[Staff], x: float, y: float) -> int | None:
    """Indice de la portée à laquelle appartient un symbole placé en (x, y)."""
    best, best_distance = None, None
    for index, staff in enumerate(staves):
        if not staff.x0 - 0.5 * staff.interline <= x <= staff.x1 + staff.interline:
            continue
        distance = staff.vertical_distance(y)
        if distance <= MAX_STAFF_DISTANCE * staff.interline and (
                best_distance is None or distance < best_distance):
            best, best_distance = index, distance
    return best


def _measure_bounds(staff: Staff) -> list[tuple[float, float]]:
    """Découpe la portée en mesures d'après ses barres.

    Une mesure fait toujours plus de 2 interlignes de large : des traits plus rapprochés
    (trait de système doublé, accolade) ne créent pas de mesure.
    """
    minimum = MIN_MEASURE_WIDTH * staff.interline
    bounds = [staff.x0]
    for x in staff.barlines:
        if x - bounds[-1] > minimum:
            bounds.append(x)
    if staff.x1 - bounds[-1] > minimum:
        bounds.append(staff.x1)  # dernière mesure sans barre finale
    return list(pairwise(bounds))


def _digits_number(glyphs: list[Glyph]) -> int | None:
    """Nombre écrit par des chiffres côte à côte (de gauche à droite)."""
    if not glyphs:
        return None
    return int("".join(str(g.digit) for g in sorted(glyphs, key=lambda g: g.x)))


def _time_signature(digits: list[Glyph], staff: Staff) -> str | None:
    """Indication de mesure : deux rangées de chiffres superposées dans la portée.

    La hauteur exacte du point d'ancrage dépend de la police (positions 6 et 2 pour
    Maestro ou Opus, autre chose pour Jazz) : on cherche donc simplement deux rangées.
    """
    rows: list[list[Glyph]] = []
    for glyph in sorted(digits, key=lambda g: g.y):
        if rows and glyph.y - rows[-1][0].y <= 0.5 * staff.interline:
            rows[-1].append(glyph)
        else:
            rows.append([glyph])
    if len(rows) != 2:
        return None
    upper, lower = rows
    # Les deux nombres sont l'un au-dessus de l'autre, pas côte à côte.
    if abs(min(g.x for g in upper) - min(g.x for g in lower)) > 1.5 * staff.interline:
        return None
    return f"{_digits_number(upper)}/{_digits_number(lower)}"


def _is_multirest_bar(shape: Shape, staff: Staff) -> bool:
    """Barre épaisse horizontale sur la ligne du milieu : pause multiple."""
    rect = shape.rect
    center = staff.position((rect.y0 + rect.y1) / 2)
    return (0.3 * staff.interline <= rect.height <= 1.5 * staff.interline
            and rect.width >= 1.5 * staff.interline
            and abs(center - 4) <= 1)


_DIGITS_ONLY = re.compile(r"^\d{1,4}$")


def read_page(page: pymupdf.Page) -> VectorPage:
    """Lit une page PDF vectorielle."""
    return interpret_page(extract_primitives(page), page.number + 1)


def interpret_page(prims: PagePrimitives, page_number: int) -> VectorPage:
    """Interprète les éléments extraits d'une page (séparé de l'extraction pour pouvoir
    être testé sur des éléments fabriqués, sans police de musique)."""
    warnings: list[str] = []
    if prims.unknown_music_fonts and not any(g.symbol for g in prims.glyphs):
        # Sans symboles lisibles, les mesures trouvées ne voudraient rien dire :
        # la page est laissée à Audiveris.
        warnings.append("unreadable_music_font")
        return VectorPage(page_number, [], prims.texts, [], warnings)

    noteheads = [g for g in prims.glyphs if g.symbol and g.symbol.kind == "notehead"]
    staves = find_staves(prims.hlines)
    if not staves:
        warnings.append("no_staff_found")
        return VectorPage(page_number, [], prims.texts, [], warnings)

    barlines = find_barlines(staves, prims.vlines, prims.shapes, noteheads)
    systems_idx = group_systems(staves, barlines)

    # Chaque portée découpée en mesures vides, à remplir.
    contents = [StaffContent(staff, [Measure(a, b) for a, b in _measure_bounds(staff)])
                for staff in staves]

    def measure_at(staff_index: int, x: float) -> Measure | None:
        for measure in contents[staff_index].measures:
            if measure.x0 - 0.5 * staves[staff_index].interline <= x < measure.x1:
                return measure
        return None

    # Répartition des caractères de musique par portée puis par mesure.
    by_measure: dict[int, list[Glyph]] = {}
    staff_of: dict[int, int] = {}
    for glyph in prims.glyphs:
        index = _nearest_staff(staves, glyph.x, glyph.y)
        if index is None:
            continue
        measure = measure_at(index, glyph.x)
        if measure is None:
            continue
        by_measure.setdefault(id(measure), []).append(glyph)
        staff_of[id(measure)] = index

    # Taille habituelle des têtes de notes (pour reconnaître les petites notes).
    normal_size = median(g.size for g in noteheads) if noteheads else 0.0

    # Textes : tout ce qui est au-dessus de la première portée forme l'en-tête (titre,
    # instrument, tempo...). Un texte proche d'une portée est AUSSI rattaché à sa mesure :
    # le tempo écrit juste au-dessus de la 1re portée appartient aux deux.
    first_top = min(s.top for s in staves)
    header_lines = [t for t in prims.texts if t.y1 < first_top]
    free_texts = []
    for text in prims.texts:
        center_x, center_y = (text.x0 + text.x1) / 2, (text.y0 + text.y1) / 2
        index = _nearest_staff(staves, center_x, center_y)
        measure = measure_at(index, text.x0) if index is not None else None
        if measure is not None:
            _attach_text(measure, text, staves[index])
        elif text.y1 >= first_top:
            free_texts.append(text)

    # Interprétation, portée par portée, en suivant les parties d'un système à l'autre :
    # la clé et l'armure se poursuivent sur la portée de même rang du système suivant.
    systems = [[contents[i] for i in members] for members in systems_idx]
    if len({len(system) for system in systems}) > 1:
        warnings.append("variable_staff_count")
    state: dict[int, dict] = {}
    for system in systems:
        for rank, content in enumerate(system):
            part_state = state.setdefault(rank, {"clef": None, "clef_position": None,
                                                 "key": 0})
            _interpret_staff(content, part_state, by_measure, prims.shapes, normal_size,
                             warnings)

    return VectorPage(page_number, systems, header_lines, free_texts, sorted(set(warnings)))


def _key_signature(accidentals: list[Glyph], heads: list[Glyph], first_event: float,
                   staff: Staff, state: dict) -> tuple[set[int], int] | None:
    """Armure écrite en tête de mesure : (identifiants des altérations, dièses + / bémols -).

    Une armure suit toujours le même ordre : fa, do, sol, ré, la, mi, si pour les dièses,
    et l'inverse pour les bémols, chaque signe serré contre le précédent. Des bécarres
    d'annulation peuvent la précéder.
    Un signe ISOLÉ collé à une note de même hauteur est l'altération de cette note
    (fa♯ en tête de mesure en do majeur), pas une armure ; à partir de deux signes dans
    l'ordre, c'est une armure, même si une note de même hauteur suit de près
    (ré♯ juste après une armure de 4 dièses).
    Renvoie None s'il n'y a pas d'armure dans la mesure.
    """
    if state["clef"] in (None, "percussion"):
        return None
    candidates = [a for a in accidentals if a.x < first_event]
    if not candidates:
        return None
    gap = KEY_SIGNATURE_GAP * staff.interline
    run: list[Glyph] = []
    # Bécarres d'annulation en tête.
    index = 0
    while index < len(candidates) and candidates[index].symbol.name == "natural" and (
            not run or candidates[index].x - run[-1].x <= gap):
        run.append(candidates[index])
        index += 1
    kind = candidates[index].symbol.name if index < len(candidates) else None
    order = {"sharp": pitch.SHARP_ORDER, "flat": pitch.FLAT_ORDER}.get(kind or "")
    count = 0
    if order:
        for acc in candidates[index:]:
            if acc.symbol.name != kind or count >= 7:
                break
            if run and acc.x - run[-1].x > gap:
                break
            step, _ = pitch.pitch_at(state["clef"], state["clef_position"],
                                     round(staff.position(acc.y)))
            if step != order[count]:
                break
            run.append(acc)
            count += 1
    if not run:
        return None
    if len(run) == 1 and _close_to_same_note(run[0], heads, staff):
        return None
    return {id(a) for a in run}, count if kind == "sharp" else -count


def _close_to_same_note(acc: Glyph, heads: list[Glyph], staff: Staff) -> bool:
    """Vrai si une tête de note de même hauteur suit l'altération de très près."""
    position = staff.position(acc.y)
    return any(0 < head.x - acc.x <= NOTE_ACCIDENTAL_DISTANCE * staff.interline
               and abs(staff.position(head.y) - position) <= 0.5 for head in heads)


def _attach_text(measure: Measure, text: TextLine, staff: Staff) -> None:
    """Range un texte proche d'une mesure : numéro de mesure ou indication."""
    above = text.y1 <= staff.top
    near_start = text.x0 <= measure.x0 + 3 * staff.interline
    if _DIGITS_ONLY.match(text.text) and above and near_start and measure.printed_number is None:
        measure.printed_number = int(text.text)
    else:
        measure.texts.append(text.text)


def _interpret_staff(content: StaffContent, state: dict, by_measure: dict[int, list[Glyph]],
                     shapes: list[Shape], normal_size: float, warnings: list[str]) -> None:
    staff = content.staff
    il = staff.interline
    for number, measure in enumerate(content.measures):
        glyphs = sorted(by_measure.get(id(measure), []), key=lambda g: g.x)
        heads = [g for g in glyphs if g.symbol and g.symbol.kind == "notehead"]
        rests = [g for g in glyphs if g.symbol and g.symbol.kind == "rest"]
        first_event = min((g.x for g in heads + rests), default=measure.x1)

        # Clé (début de ligne ou changement).
        for g in glyphs:
            if g.symbol and g.symbol.kind == "clef" and -2 <= staff.position(g.y) <= 10:
                measure.clef = g.symbol.name
                state["clef"] = g.symbol.name
                state["clef_position"] = round(staff.position(g.y))
                if number == 0:
                    content.clef, content.clef_position = state["clef"], state["clef_position"]
        if state["clef"] is None:
            warnings.append("no_clef")
            state["clef"], state["clef_position"] = "treble", pitch.DEFAULT_CLEF_POSITION["treble"]
            if number == 0:
                content.clef, content.clef_position = state["clef"], state["clef_position"]

        # Altérations : d'abord l'armure (avant le premier événement), puis celles des notes.
        accidentals = sorted((g for g in glyphs if g.symbol and g.symbol.kind == "accidental"),
                             key=lambda g: g.x)
        signature = _key_signature(accidentals, heads, first_event, staff, state)
        if signature is not None:
            in_signature, measure.key_fifths = signature
            state["key"] = measure.key_fifths
            accidentals = [a for a in accidentals if id(a) not in in_signature]
        attached: dict[int, Glyph] = {}
        for acc in accidentals:
            acc_pos = staff.position(acc.y)
            owner = next((h for h in heads
                          if 0 < h.x - acc.x <= ACCIDENTAL_REACH * il
                          and abs(staff.position(h.y) - acc_pos) <= 0.5
                          and id(h) not in attached), None)
            if owner is not None:
                attached[id(owner)] = acc

        # Indication de mesure.
        digits_in_staff = [g for g in glyphs if g.digit is not None and -1 <= staff.position(g.y) <= 9]
        common = next((g for g in glyphs if g.symbol and g.symbol.kind == "time"), None)
        if common is not None:
            measure.time_signature = "4/4" if common.symbol.name == "common" else "2/2"
        else:
            measure.time_signature = _time_signature(digits_in_staff, staff)

        # Pause multiple : barre épaisse sans aucune note, nombre écrit au-dessus.
        hbar = any(g.symbol and g.symbol.kind == "multirest" for g in glyphs) or any(
            measure.x0 <= s.rect.x0 and s.rect.x1 <= measure.x1 + 0.5 * il
            and _is_multirest_bar(s, staff) for s in shapes)
        if hbar and not heads:
            measure.is_multirest = True
            above = [g for g in glyphs if g.digit is not None and staff.position(g.y) > 9]
            numbers = [int(t) for t in measure.texts if _DIGITS_ONLY.match(t)]
            measure.multirest = _digits_number(above) or (numbers[0] if numbers else None)
            if numbers and measure.multirest == numbers[0]:
                measure.texts.remove(str(numbers[0]))
            if measure.multirest is None:
                warnings.append("multirest_count_missing")

        # Notes.
        carried: dict[tuple[str, int], int] = {}   # altérations valables jusqu'à la barre
        percussion = state["clef"] == "percussion"
        for head in heads:
            position, centered = _rounded_position(staff, head.y)
            if not centered:
                warnings.append("off_position")
            note = Note(x=head.x, position=position, head=head.symbol.name,
                        small=bool(normal_size) and head.size < SMALL_NOTE_RATIO * normal_size)
            accidental = attached.get(id(head))
            if accidental is not None:
                note.accidental = accidental.symbol.name
            if not percussion and not head.percussion and head.symbol.name not in ("slash", "x"):
                note.step, note.octave = pitch.pitch_at(state["clef"], state["clef_position"],
                                                        position)
                key = (note.step, note.octave)
                if note.accidental is not None:
                    carried[key] = pitch.ACCIDENTAL_ALTER[note.accidental]
                note.alter = carried.get(key, pitch.key_alter(state["key"], note.step))
            measure.notes.append(note)

        measure.rests = [Rest(g.x, g.symbol.name) for g in rests]
        measure.measure_repeat = any(g.symbol and g.symbol.kind == "repeat" for g in glyphs)
        measure.symbols = [g.symbol.name for g in glyphs if g.symbol and g.symbol.kind in
                           ("dynamic", "articulation", "navigation", "tremolo")]

