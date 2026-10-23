"""Lecture d'une page vectorielle : portées, mesures, clés, armures, chiffrages,
pauses multiples, notes (hauteur écrite exacte et durée), silences et textes.

Tâche 4b-1 : structure et hauteurs. Tâche 4b-2 : durées (voir rhythm.py), accords,
liaisons de prolongation, contrôle de la durée de chaque mesure.
"""

import re
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from statistics import median

import pymupdf

from recomuse.vector import pitch, rhythm
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

# Une tête plus petite que 85 % de la taille normale est une petite note (appoggiature,
# note de réplique). La taille normale d'une police de musique est la hauteur de la portée,
# soit 4 interlignes (vérifié sur tout le corpus) : on compare donc à la portée de la note,
# car un conducteur peut avoir des portées de tailles différentes.
SMALL_NOTE_RATIO = 0.85
NORMAL_FONT_SIZE = 4.0

# Écart maximal entre deux signes d'une armure, en interlignes.
KEY_SIGNATURE_GAP = 1.8

# Une altération à moins de 1,6 interligne d'une note de même hauteur est celle de la note.
NOTE_ACCIDENTAL_DISTANCE = 1.6

# Largeur minimale d'une mesure, en interlignes.
MIN_MEASURE_WIDTH = 2.0

# Écart toléré entre la position mesurée d'un symbole et une ligne / un interligne.
POSITION_TOLERANCE = 0.3

# Un chiffre de nolet est à moins de 4,5 interlignes de la portée (plus loin : numéro de
# page, repère...).
TUPLET_MARK_DISTANCE = 4.5

# Des têtes sans hampe (rondes) à moins de 0,5 interligne l'une de l'autre forment un accord.
CHORD_X_TOLERANCE = 0.5

# Avertissements (codes traduits par l'interface).
#   no_staff_found           : aucune portée de 5 lignes
#   unreadable_music_font    : police de musique intégrée sans table de caractères
#   no_clef                  : portée sans clé lisible, clé de sol supposée
#   multirest_count_missing  : pause multiple dont le nombre n'a pas été trouvé
#   off_position             : symbole entre deux positions (à vérifier)
#   variable_staff_count     : systèmes de tailles différentes (conducteur à portées masquées)
#   stem_missing             : tête noire ou blanche sans hampe trouvée
# Les mesures de durée incorrecte sont listées par partie : VectorScore.duration_mismatches().


@dataclass
class Note:
    """Une tête de note avec sa hauteur écrite et sa durée."""

    x: float
    position: int                  # 0 = ligne du bas de la portée
    head: str                      # black, half, whole, breve, x, slash
    step: str | None = None        # None sur une portée de percussions
    octave: int | None = None
    alter: int = 0                 # -1 bémol, 0, +1 dièse (armure et altérations comprises)
    accidental: str | None = None  # altération écrite devant la note
    small: bool = False            # petite note : appoggiature, ou réplique si `cue`
    cue: bool = False              # petite note de réplique (compte dans la mesure)
    duration: Fraction | None = None   # en noires (1 = noire, 1/2 = croche...)
    dots: int = 0
    stem: str | None = None        # "up", "down" ou None (ronde)
    chord: bool = False            # vrai pour les notes d'un accord après la première
    tuplet: tuple[int, int] | None = None   # (3, 2) : triolet
    tie_start: bool = False        # liée à la note suivante
    tie_stop: bool = False         # liée à la note précédente
    voice: int = 1

    @property
    def name(self) -> str | None:
        if self.step is None or self.octave is None:
            return None
        return pitch.pitch_name(self.step, self.octave, self.alter)

    @property
    def grace(self) -> bool:
        """Appoggiature : petite note qui ne compte pas dans la durée de la mesure."""
        return self.small and not self.cue


def _counted(event) -> Fraction | None:
    """Durée d'une note ou d'un silence dans le total de la mesure (0 pour une appoggiature)."""
    if isinstance(event, Note) and event.grace:
        return Fraction(0)
    return event.duration


@dataclass
class Rest:
    x: float
    value: str                     # whole, half, quarter, eighth, 16th...
    position: float = 4.0          # hauteur sur la portée (4 = ligne du milieu)
    duration: Fraction | None = None
    dots: int = 0
    tuplet: tuple[int, int] | None = None
    voice: int = 1


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
    expected_duration: Fraction | None = None   # durée d'après le chiffrage en vigueur
    voices: int = 1
    open_end: bool = False               # fin de ligne sans barre de mesure
    percussion: bool = False             # mesure d'une portée de percussions
    # Chiffres isolés écrits en texte près de la portée : (abscisse, valeur). Ce sont des
    # nolets (« 3 » d'un triolet) ou le nombre d'une pause multiple.
    digit_marks: list[tuple[float, int]] = field(default_factory=list)

    @property
    def full_rest(self) -> bool:
        """Mesure entière de silence (une pause seule)."""
        return not self.notes and [r.value for r in self.rests] == ["whole"]

    @property
    def length(self) -> int:
        """Nombre de mesures réellement représentées (une pause multiple en vaut plusieurs)."""
        return self.multirest if self.is_multirest and self.multirest else 1

    @property
    def duration(self) -> Fraction | None:
        """Durée lue de la 1re voix (en noires), ou None si une valeur manque."""
        if self.is_multirest or self.measure_repeat or self.full_rest:
            return self.expected_duration
        total = Fraction(0)
        for event in self.events(voice=1):
            value = _counted(event)
            if value is None:
                return None
            total += value
        return total

    @property
    def duration_ok(self) -> bool | None:
        """Vrai si la durée lue est celle du chiffrage ; None si on ne peut pas le savoir
        (valeur manquante, chiffrage inconnu, portée de percussions)."""
        if self.percussion or self.duration is None or self.expected_duration is None:
            return None
        return self.duration == self.expected_duration

    def events(self, voice: int | None = None) -> list:
        """Notes (premières de chaque accord) et silences, dans l'ordre, d'une voix ou de toutes."""
        items = [n for n in self.notes if not n.chord] + list(self.rests)
        if voice is not None:
            items = [item for item in items if item.voice == voice]
        return sorted(items, key=lambda item: item.x)


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


@dataclass
class _Page:
    """Ce que la lecture d'une page partage entre toutes ses portées."""

    by_measure: dict[int, list[Glyph]]
    shapes: list[Shape]
    head_width: float                       # largeur d'une tête noire, en interlignes
    stems: dict[int, rhythm.Stem]           # id(tête) → hampe
    tie_from: dict[int, Glyph | None]       # id(tête d'arrivée) → tête de départ (None : début de ligne)
    tie_starts: set[int]                    # id des têtes qui commencent une liaison
    notes_by_head: dict[int, Note] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


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


def _measure_bounds(staff: Staff) -> list[Measure]:
    """Découpe la portée en mesures (vides) d'après ses barres.

    Une mesure fait toujours plus de 2 interlignes de large : des traits plus rapprochés
    (trait de système doublé, accolade) ne créent pas de mesure. La portion après la
    dernière barre est marquée « open_end » : c'est souvent un simple rappel de l'armure ou
    de la clé de la ligne suivante, écarté s'il ne contient ni note ni silence.
    """
    minimum = MIN_MEASURE_WIDTH * staff.interline
    bounds = [staff.x0]
    for x in staff.barlines:
        if x - bounds[-1] > minimum:
            bounds.append(x)
    open_end = staff.x1 - bounds[-1] > minimum
    if open_end:
        bounds.append(staff.x1)
    measures = [Measure(a, b) for a, b in pairwise(bounds)]
    if open_end:
        measures[-1].open_end = True
    return measures


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


def _signature_duration(signature: str | None) -> Fraction | None:
    """Durée d'une mesure en noires : « 3/4 » → 3, « 6/8 » → 3, « 2/2 » → 4."""
    if not signature:
        return None
    beats, beat_type = signature.split("/")
    return Fraction(int(beats) * 4, int(beat_type))


def _is_multirest_bar(shape: Shape, staff: Staff) -> bool:
    """Barre épaisse horizontale sur la ligne du milieu : pause multiple."""
    rect = shape.rect
    center = staff.position((rect.y0 + rect.y1) / 2)
    return (0.3 * staff.interline <= rect.height <= 1.5 * staff.interline
            and rect.width >= 1.5 * staff.interline
            and abs(center - 4) <= 1)


_DIGITS_ONLY = re.compile(r"^\d{1,4}$")


# État de chaque partie (rang de portée) qui se poursuit d'un système et d'une page à
# l'autre : clé, armure, chiffrage, liaisons qui sortent en fin de ligne.
PartStates = dict[int, dict]


def new_part_state() -> dict:
    return {"clef": None, "clef_position": None, "key": 0, "time": None, "pending_ties": {}}


def read_page(page: pymupdf.Page, states: PartStates | None = None) -> VectorPage:
    """Lit une page PDF vectorielle.

    `states` : état des parties à la fin de la page précédente (clé, armure, chiffrage...),
    mis à jour en place ; None pour une page lue seule.
    """
    return interpret_page(extract_primitives(page), page.number + 1, states)


def interpret_page(prims: PagePrimitives, page_number: int,
                   states: PartStates | None = None) -> VectorPage:
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
    contents = [StaffContent(staff, _measure_bounds(staff)) for staff in staves]

    def measure_at(staff_index: int, x: float) -> Measure | None:
        for measure in contents[staff_index].measures:
            if measure.x0 - 0.5 * staves[staff_index].interline <= x < measure.x1:
                return measure
        return None

    # Répartition des caractères de musique par portée puis par mesure.
    by_measure: dict[int, list[Glyph]] = {}
    staff_of_glyph: dict[int, int] = {}
    for glyph in prims.glyphs:
        index = _nearest_staff(staves, glyph.x, glyph.y)
        if index is None:
            continue
        measure = measure_at(index, glyph.x)
        if measure is None:
            continue
        by_measure.setdefault(id(measure), []).append(glyph)
        staff_of_glyph[id(glyph)] = index

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

    # Rythmes : hampes (sans les barres de mesure), ligatures, crochets, liaisons.
    interline = median(s.interline for s in staves)
    barline_keys = {(round(x, 2), round(y0, 2), round(y1, 2)) for x, y0, y1 in barlines}
    stem_lines = [v for v in prims.vlines
                  if (round(v.x, 2), round(v.y0, 2), round(v.y1, 2)) not in barline_keys]
    black_heads = [g for g in noteheads if g.symbol.name == "black"]
    head_width = rhythm.estimate_head_width(black_heads, stem_lines, interline)
    stems = rhythm.find_stems(noteheads, stem_lines, interline, head_width)
    flags = [g for g in prims.glyphs if g.symbol and g.symbol.kind == "flag"]
    rhythm.attach_beams_and_flags(list({id(s): s for s in stems.values()}.values()),
                                  prims.beams, flags, interline)

    def position_of(head: Glyph) -> tuple[int | None, int]:
        index = staff_of_glyph.get(id(head))
        return index, round(staves[index].position(head.y)) if index is not None else 0

    tie_from: dict[int, Glyph | None] = {}
    tie_starts: set[int] = set()
    for start, end in rhythm.find_ties(noteheads, prims.curves, interline, head_width,
                                       position_of):
        if start is not None:
            tie_starts.add(id(start))
        if end is not None:
            tie_from[id(end)] = start

    page = _Page(
        by_measure=by_measure, shapes=prims.shapes,
        head_width=head_width, stems=stems, tie_from=tie_from, tie_starts=tie_starts,
        warnings=warnings,
    )

    # Interprétation, portée par portée, en suivant les parties d'un système à l'autre :
    # la clé, l'armure et le chiffrage se poursuivent sur la portée de même rang.
    systems = [[contents[i] for i in members] for members in systems_idx]
    if len({len(system) for system in systems}) > 1:
        warnings.append("variable_staff_count")
    states = {} if states is None else states
    for system in systems:
        for rank, content in enumerate(system):
            _interpret_staff(content, states.setdefault(rank, new_part_state()), page)

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
    elif _DIGITS_ONLY.match(text.text) and staff.vertical_distance(
            (text.y0 + text.y1) / 2) <= TUPLET_MARK_DISTANCE * staff.interline:
        measure.digit_marks.append(((text.x0 + text.x1) / 2, int(text.text)))
    else:
        measure.texts.append(text.text)


def _interpret_staff(content: StaffContent, state: dict, page: _Page) -> None:
    staff = content.staff
    il = staff.interline
    warnings = page.warnings
    for number, measure in enumerate(content.measures):
        glyphs = sorted(page.by_measure.get(id(measure), []), key=lambda g: g.x)
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

        # Indication de mesure (elle reste en vigueur jusqu'à la suivante).
        digits_in_staff = [g for g in glyphs if g.digit is not None and -1 <= staff.position(g.y) <= 9]
        common = next((g for g in glyphs if g.symbol and g.symbol.kind == "time"), None)
        if common is not None:
            measure.time_signature = "4/4" if common.symbol.name == "common" else "2/2"
        else:
            measure.time_signature = _time_signature(digits_in_staff, staff)
        if measure.time_signature:
            state["time"] = measure.time_signature
        measure.expected_duration = _signature_duration(state["time"])

        # Pause multiple : barre épaisse sans aucune note, nombre écrit au-dessus.
        hbar = any(g.symbol and g.symbol.kind == "multirest" for g in glyphs) or any(
            measure.x0 <= s.rect.x0 and s.rect.x1 <= measure.x1 + 0.5 * il
            and _is_multirest_bar(s, staff) for s in page.shapes)
        digits_outside = [g for g in glyphs if g.digit is not None
                          and not -1 <= staff.position(g.y) <= 9]
        if hbar and not heads:
            measure.is_multirest = True
            above = [g for g in digits_outside if staff.position(g.y) > 9]
            numbers = [value for _, value in measure.digit_marks]
            measure.multirest = _digits_number(above) or (numbers[0] if numbers else None)
            measure.digit_marks = []
            if measure.multirest is None:
                warnings.append("multirest_count_missing")
            digits_outside = []

        # Notes : hauteur.
        carried: dict[tuple[str, int], int] = {}   # altérations valables jusqu'à la barre
        percussion = state["clef"] == "percussion"
        measure.percussion = percussion
        for head in heads:
            position, centered = _rounded_position(staff, head.y)
            if not centered:
                warnings.append("off_position")
            note = Note(x=head.x, position=position, head=head.symbol.name,
                        small=head.size < SMALL_NOTE_RATIO * NORMAL_FONT_SIZE * il)
            accidental = attached.get(id(head))
            if accidental is not None:
                note.accidental = accidental.symbol.name
            note.tie_start = id(head) in page.tie_starts
            note.tie_stop = id(head) in page.tie_from
            if not percussion and not head.percussion and head.symbol.name not in ("slash", "x"):
                note.step, note.octave = pitch.pitch_at(state["clef"], state["clef_position"],
                                                        position)
                key = (note.step, note.octave)
                if note.accidental is not None:
                    carried[key] = pitch.ACCIDENTAL_ALTER[note.accidental]
                note.alter = carried.get(key, pitch.key_alter(state["key"], note.step))
                if note.tie_stop and note.accidental is None:
                    # Une note liée garde l'altération de la note dont elle part, même
                    # au-delà de la barre de mesure ou en début de ligne.
                    start = page.tie_from[id(head)]
                    if start is not None and id(start) in page.notes_by_head:
                        note.alter = page.notes_by_head[id(start)].alter
                    elif key in state["pending_ties"]:
                        note.alter = state["pending_ties"][key]
            page.notes_by_head[id(head)] = note
            measure.notes.append(note)

        measure.rests = [Rest(g.x, g.symbol.name, position=staff.position(g.y)) for g in rests]
        _read_rhythms(measure, heads, rests, glyphs, digits_outside, staff, page)

        measure.measure_repeat = any(g.symbol and g.symbol.kind == "repeat" for g in glyphs)
        measure.symbols = [g.symbol.name for g in glyphs if g.symbol and g.symbol.kind in
                           ("dynamic", "articulation", "navigation", "tremolo")]

    # Rappel de fin de ligne : pas une mesure.
    last = content.measures[-1] if content.measures else None
    if last is not None and last.open_end and not (
            last.notes or last.rests or last.is_multirest or last.measure_repeat):
        content.measures.pop()

    # Liaisons qui sortent en fin de ligne : la note d'arrivée, au début de la ligne
    # suivante, gardera la même altération.
    state["pending_ties"] = {
        (n.step, n.octave): n.alter
        for m in content.measures[-1:] for n in m.notes if n.tie_start and n.step
    }


def _read_rhythms(measure: Measure, heads: list[Glyph], rests: list[Glyph],
                  glyphs: list[Glyph], digits_outside: list[Glyph], staff: Staff,
                  page: _Page) -> None:
    """Durées des notes et des silences d'une mesure, nolets, voix."""
    il = staff.interline
    hw = page.head_width
    notes_by_head = {id(h): page.notes_by_head[id(h)] for h in heads}
    dots = [g for g in glyphs if g.symbol and g.symbol.kind == "dot"]
    used_dots: set[int] = set()

    # Accords : têtes d'une même hampe, ou rondes empilées.
    chords: list[list[Glyph]] = []
    by_stem: dict[int, list[Glyph]] = {}
    for head in heads:
        stem = page.stems.get(id(head))
        if stem is not None:
            by_stem.setdefault(id(stem), []).append(head)
        else:
            group = next((c for c in chords if id(c[0]) not in page.stems
                          and abs(c[0].x - head.x) <= CHORD_X_TOLERANCE * il), None)
            if group is not None:
                group.append(head)
            else:
                chords.append([head])
    chords += list(by_stem.values())

    # Valeur de chaque accord.
    chord_of_note: dict[int, list[Note]] = {}
    for chord in chords:
        stem = page.stems.get(id(chord[0]))
        name = chord[0].symbol.name
        if stem is None and name in ("black", "half", "x"):
            page.warnings.append("stem_missing")
        width = hw * (1.4 if name in ("whole", "breve") else 1.0)
        x_right = max(h.x for h in chord) + width * il
        n_dots = rhythm.count_dots(x_right, [h.y for h in chord], dots, used_dots, il)
        value = rhythm.dotted(rhythm.base_value(name, stem), n_dots)
        notes = sorted((notes_by_head[id(h)] for h in chord), key=lambda n: n.position)
        for index, note in enumerate(notes):
            note.duration = value
            note.dots = n_dots
            note.stem = stem.direction if stem else None
            note.chord = index > 0
        chord_of_note[id(notes[0])] = notes

    for glyph, rest in zip(rests, measure.rests, strict=True):
        rest.dots = rhythm.count_dots(glyph.x + 1.1 * il, [glyph.y], dots, used_dots, il)
        rest.duration = rhythm.dotted(rhythm.REST_VALUE[rest.value], rest.dots)

    # Nolets : un chiffre au-dessus ou en dessous de la portée, sur un groupe de notes.
    events = measure.events()
    head_of_note = {id(notes_by_head[id(h)]): h for h in heads}
    # Un nolet raccourcit les notes : il n'a de sens que si la mesure est trop longue sans lui
    # (un chiffre isolé peut aussi être un doigté ou un numéro).
    marks = [(g.x, g.digit) for g in digits_outside
             if staff.vertical_distance(g.y) <= TUPLET_MARK_DISTANCE * il] + measure.digit_marks
    total = sum((_counted(e) for e in events if e.duration is not None), Fraction(0))
    if measure.expected_duration is not None and total <= measure.expected_duration:
        marks = []
    for x, count in marks:
        normal = rhythm.TUPLET_NORMAL.get(count)
        if normal is None or not events:
            continue
        group = _tuplet_group(events, x, count, page, head_of_note)
        ratio = Fraction(normal, count)
        for event in group:
            if event.tuplet is not None or event.duration is None:
                continue
            for item in chord_of_note.get(id(event), [event]):
                item.duration *= ratio
                item.tuplet = (count, normal)

    # Une pause seule vaut toute la mesure, quel que soit le chiffrage.
    if measure.full_rest and measure.expected_duration is not None:
        measure.rests[0].duration = measure.expected_duration

    _detect_cue_notes(measure)
    _split_voices(measure, chord_of_note)


def _tuplet_group(events: list, x: float, count: int, page: _Page,
                  head_of_note: dict[int, Glyph]) -> list:
    """Notes et silences concernés par un chiffre de nolet.

    Si la note la plus proche du chiffre est ligaturée, le nolet couvre son groupe de
    ligature ; sinon, les `count` notes ou silences consécutifs centrés sur le chiffre.
    """
    def stem_of(event) -> rhythm.Stem | None:
        head = head_of_note.get(id(event))
        return page.stems.get(id(head)) if head is not None else None

    nearest = min(range(len(events)), key=lambda i: abs(events[i].x - x))
    stem = stem_of(events[nearest])
    if stem is not None and stem.beams:
        beam_ids = {id(b) for b in stem.beams}
        return [e for e in events
                if (other := stem_of(e)) is not None and beam_ids & {id(b) for b in other.beams}]
    start = max(0, min(nearest - count // 2, len(events) - count))
    return events[start:start + count]


def _detect_cue_notes(measure: Measure) -> None:
    """Petites notes qui remplissent la mesure : ce sont des notes de réplique (« cue »),
    écrites pour aider à compter, et non des appoggiatures. Elles comptent alors dans la
    durée de la mesure."""
    small = [n for n in measure.notes if n.small and not n.chord]
    if not small or measure.duration_ok is not False:
        return
    with_small = sum((e.duration for e in measure.events(voice=1) if e.duration is not None),
                     Fraction(0))
    if with_small == measure.expected_duration:
        for note in measure.notes:
            if note.small:
                note.cue = True


def _split_voices(measure: Measure, chord_of_note: dict[int, list[Note]]) -> None:
    """Deux voix sur une portée : la voix 1 au-dessus (hampes vers le haut), la voix 2
    en dessous (hampes vers le bas).

    On ne sépare que si la mesure est trop longue et que chaque voix donne alors
    exactement la durée attendue. Une note sans hampe (ronde) va dans la voix du dessus si
    elle est plus haute que les notes à hampe, sinon dans celle du dessous ; un silence,
    selon qu'il est décalé vers le haut ou vers le bas de la ligne du milieu.
    """
    expected = measure.expected_duration
    if expected is None or measure.duration in (None, expected):
        return
    events = [e for e in measure.events() if _counted(e) != 0 or isinstance(e, Rest)]
    if any(e.duration is None for e in events):
        return
    stemmed = [e.position for e in events if isinstance(e, Note) and e.stem]
    middle = median(stemmed) if stemmed else 4

    def voice_of(event, centered_rest_voice: int) -> int:
        if isinstance(event, Note):
            if event.stem == "up":
                return 1
            if event.stem == "down":
                return 2
            return 1 if event.position > middle else 2
        if event.position > 4.5:
            return 1
        if event.position < 3.5:
            return 2
        return centered_rest_voice

    def duration(event) -> Fraction:
        # Une pause dans une voix vaut toute la mesure de cette voix.
        if isinstance(event, Rest) and event.value == "whole":
            return expected
        return event.duration

    for centered_rest_voice in (1, 2):
        totals = {1: Fraction(0), 2: Fraction(0)}
        for event in events:
            totals[voice_of(event, centered_rest_voice)] += duration(event)
        if totals[1] == expected and totals[2] == expected:
            for event in events:
                for item in chord_of_note.get(id(event), [event]):
                    item.voice = voice_of(event, centered_rest_voice)
                if isinstance(event, Rest) and event.value == "whole":
                    event.duration = expected
            measure.voices = 2
            return
