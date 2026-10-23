"""Comparaison entre les parties d'un même morceau.

Toutes les parties d'un morceau ont la même structure : même nombre de mesures, mêmes
changements de chiffrage aux mêmes endroits, mêmes lettres de répétition, changements
d'armure aux mêmes endroits (les armures elles-mêmes diffèrent : les instruments
transpositeurs n'ont pas la même). Une partie qui s'écarte des autres a presque sûrement
été mal lue : par exemple une pause multiple comptée pour une seule mesure.

Méthode :
1. chaque partie devient une suite d'« unités » (une par mesure, une pause multiple de N
   en donnant N), chacune avec ses repères : lettre de répétition, chiffrage écrit,
   changement d'armure, silence ;
2. la référence est la partie dont la longueur est la plus fréquente (une partie lue par
   la lecture vectorielle de préférence) ;
3. chaque partie est alignée sur la référence (programmation dynamique, comme pour
   comparer deux textes) : un repère qui ne coïncide pas coûte cher, une mesure en plus ou
   en moins coûte 1 ;
4. les mesures en trop ou en moins, et les chiffrages qui diffèrent de ce que dit la
   majorité des parties, deviennent des problèmes (avec une correction proposée quand une
   pause voisine explique l'écart).
"""

from collections import Counter
from dataclasses import dataclass, replace

from recomuse.model.score import Measure, Part, ScoreModel
from recomuse.model.split import normalized
from recomuse.validation.issues import Fix, Issue, ValidationReport

# Coûts de l'alignement.
GAP_COST = 1.0            # une mesure en plus ou en moins
MARK_CONFLICT = 3.0       # deux lettres de répétition différentes
MARK_MISSING = 0.7        # lettre présente d'un côté seulement (mal lue de l'autre ?)
TIME_CONFLICT = 1.5       # chiffrages différents (ou écrit d'un côté seulement)
KEY_CONFLICT = 0.7        # changement d'armure d'un côté seulement
REST_CONFLICT = 0.3       # silence d'un côté, musique de l'autre (normal entre instruments)
# Un écart placé contre un silence coûte un peu moins : quand plusieurs places reviennent au
# même, on choisit celle où une pause mal comptée explique l'écart.
REST_GAP_BONUS = 0.05


@dataclass(frozen=True)
class Unit:
    """Une mesure « dépliée » d'une partie (une pause multiple de 8 donne 8 unités)."""

    measure: Measure
    offset: int               # rang dans la pause multiple (0 pour une mesure simple)
    time: str | None          # chiffrage écrit dans la mesure (« 3/4 »)
    key_change: bool
    mark: str | None
    rest: bool


@dataclass
class PartRef:
    """Une partie à comparer, avec un nom pour les messages."""

    label: str
    part: Part
    source: str = "vector"    # « vector » si toutes ses pages ont été lues vectoriellement


def units(part: Part) -> list[Unit]:
    """Suite des unités d'une partie, chacune avec ses repères."""
    result = []
    for measure in part.measures:
        time = next((f"{s.value['beats']}/{s.value['beat_type']}" for s in measure.attributes
                     if s.kind == "time"), None)
        key = any(s.kind == "key" for s in measure.attributes)
        rest = _rest_like(measure)
        for offset in range(measure.length):
            first = offset == 0
            result.append(Unit(measure, offset, time if first else None, key and first,
                               measure.marks[0] if first and measure.marks else None, rest))
    return result


def _cost(a: Unit, b: Unit) -> float:
    cost = 0.0
    if a.mark != b.mark:
        cost += MARK_CONFLICT if a.mark and b.mark else MARK_MISSING
    if a.time != b.time:
        cost += TIME_CONFLICT
    if a.key_change != b.key_change:
        cost += KEY_CONFLICT
    if a.rest != b.rest:
        cost += REST_CONFLICT
    return cost


def _gap_in_a(a: list[Unit], i: int) -> float:
    """Coût d'une unité de b sans correspondant, entre a[i-1] et a[i]."""
    near_rest = (i > 0 and a[i - 1].rest) or (i < len(a) and a[i].rest)
    return GAP_COST - REST_GAP_BONUS if near_rest else GAP_COST


def _extra_in_a(a: list[Unit], i: int) -> float:
    """Coût de l'unité a[i] sans correspondant dans b."""
    return GAP_COST - REST_GAP_BONUS if a[i].rest else GAP_COST


def align(a: list[Unit], b: list[Unit]) -> list[tuple[int | None, int | None]]:
    """Alignement de deux suites : paires (rang dans a, rang dans b), None = absente.

    Programmation dynamique : table[i][j] = coût minimal pour aligner les i premières
    unités de a sur les j premières de b ; on remonte ensuite la table pour lire les paires."""
    n, m = len(a), len(b)
    table = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        table[i][0] = table[i - 1][0] + _extra_in_a(a, i - 1)
    for j in range(1, m + 1):
        table[0][j] = table[0][j - 1] + _gap_in_a(a, 0)
    for i in range(1, n + 1):
        row, previous = table[i], table[i - 1]
        extra, gap = _extra_in_a(a, i - 1), _gap_in_a(a, i)
        for j in range(1, m + 1):
            row[j] = min(previous[j - 1] + _cost(a[i - 1], b[j - 1]),
                         previous[j] + extra, row[j - 1] + gap)
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(table[i][j] - (table[i - 1][j - 1]
                                                   + _cost(a[i - 1], b[j - 1]))) < 1e-9:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and abs(table[i][j] - (table[i - 1][j] + _extra_in_a(a, i - 1))) < 1e-9:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return pairs[::-1]


def part_refs(models: list[ScoreModel]) -> list[PartRef]:
    """Parties de plusieurs modèles (un modèle par partie, ou un conducteur)."""
    refs = []
    for model in models:
        source = "vector" if model.pages and all(p.source == "vector" for p in model.pages) \
            else "audiveris"
        seen: set[str] = set()
        for part in model.parts:
            label = part.name or model.instrument or f"{part.id}"
            # Portées suivantes d'un même instrument (main gauche du piano) : elles peuvent
            # n'exister que sur une partie des lignes, la portée du haut suffit.
            if label in seen:
                continue
            seen.add(label)
            refs.append(PartRef(label=label, part=part, source=source))
    return refs


def group_by_title(models: list[ScoreModel]) -> dict[str, list[ScoreModel]]:
    """Regroupe les modèles d'un même morceau (même titre)."""
    groups: dict[str, list[ScoreModel]] = {}
    for model in models:
        groups.setdefault(normalized(model.title) or "?", []).append(model)
    return groups


def _shared_marks_only(sequences: list[list[Unit]]) -> list[list[Unit]]:
    """Ne garde que les lettres de répétition présentes dans au moins la moitié des parties.
    Un accord écrit au-dessus de la portée (« E », « B7 ») ressemble à une lettre : il
    n'apparaît que dans les parties d'accompagnement, il ne doit pas guider l'alignement."""
    support = Counter(mark for seq in sequences for mark in {u.mark for u in seq if u.mark})
    shared = {mark for mark, count in support.items() if count >= len(sequences) / 2}
    return [[u if u.mark is None or u.mark in shared else replace(u, mark=None) for u in seq]
            for seq in sequences]


def compare_parts(refs: list[PartRef]) -> ValidationReport:
    """Compare les parties d'un même morceau et signale celles qui s'écartent.
    Chaque problème porte dans details["ref_index"] le rang de sa partie dans `refs`."""
    if len(refs) < 2:
        return ValidationReport([])
    sequences = _shared_marks_only([units(ref.part) for ref in refs])
    lengths = Counter(len(s) for s in sequences)
    usual = lengths.most_common(1)[0][0]
    reference = _reference(refs, sequences, usual)
    ref_units = sequences[reference]

    alignments = {k: align(seq, ref_units) for k, seq in enumerate(sequences) if k != reference}
    issues: list[Issue] = []
    agreeing = sum(1 for s in sequences if len(s) == usual)
    for k, pairs in alignments.items():
        for issue in _gaps(refs[k], sequences[k], pairs, usual, agreeing, len(refs)):
            issue.details["ref_index"] = k
            issues.append(issue)
    issues += _time_disagreements(refs, sequences, reference, alignments)
    return ValidationReport(issues)


# Le choix de la référence coûte des alignements : on se limite à quelques candidates,
# comparées à quelques autres parties.
REFERENCE_CANDIDATES = 6


def _reference(refs: list[PartRef], sequences: list[list[Unit]], usual: int) -> int:
    """Rang de la partie de référence : parmi celles de longueur habituelle, celle qui
    demande le moins de mesures ajoutées ou retirées pour s'aligner sur les autres (une
    partie peut avoir la bonne longueur par hasard : une mesure en trop ici, une en moins
    là). À égalité, une partie lue vectoriellement."""
    candidates = sorted((k for k, s in enumerate(sequences) if len(s) == usual),
                        key=lambda k: refs[k].source != "vector")[:REFERENCE_CANDIDATES]
    if len(candidates) == 1:
        return candidates[0]
    others = candidates + [k for k in range(len(sequences)) if k not in candidates]
    others = others[:2 * REFERENCE_CANDIDATES]

    def gaps(k: int) -> int:
        return sum(sum(1 for a, b in align(sequences[o], sequences[k]) if a is None or b is None)
                   for o in others if o != k)

    return min(candidates, key=lambda k: (gaps(k), refs[k].source != "vector"))


def _rest_like(measure: Measure) -> bool:
    """Vrai pour une mesure sans musique : pause multiple, silences seuls, ou vide."""
    return measure.length > 1 or not measure.events or all(s.kind == "rest" for s in measure.events)


def _gaps(ref: PartRef, seq: list[Unit], pairs, usual: int, agreeing: int,
          total: int) -> list[Issue]:
    """Mesures en moins (unités de la référence sans correspondant) ou en trop."""
    issues = []
    index = 0
    last_measure: Measure | None = None
    confidence = round(min(0.95, 0.5 + 0.45 * agreeing / total), 2)
    while index < len(pairs):
        mine, theirs = pairs[index]
        if mine is not None and theirs is not None:
            last_measure = seq[mine].measure
            index += 1
            continue
        missing = mine is None
        run = 0
        while index < len(pairs) and (pairs[index][0] is None) == missing \
                and (pairs[index][0] is None or pairs[index][1] is None):
            run += 1
            index += 1
        if missing:
            next_measure = next((seq[p[0]].measure for p in pairs[index:]
                                 if p[0] is not None), None)
            issues.append(_missing_issue(ref, run, last_measure, next_measure, usual, confidence))
        else:
            extra_units = [seq[p[0]] for p in pairs[index - run:index]]
            issues.append(_extra_issue(ref, extra_units, usual, confidence))
            last_measure = extra_units[-1].measure
    return issues


def _missing_issue(ref: PartRef, count: int, before: Measure | None, after: Measure | None,
                   usual: int, confidence: float) -> Issue:
    numbers = [m.number for m in (before, after) if m is not None]
    issue = Issue(code="part_measures_missing", part_id=ref.label, measure_numbers=numbers,
                  severity="error", confidence=confidence,
                  details={"missing": count, "usual_length": usual})
    # Une pause juste avant ou juste après : son nombre est sans doute faux.
    for measure in (before, after):
        if measure is None or not _rest_like(measure):
            continue
        multirest = next((s for s in measure.attributes if s.kind == "multirest"), None)
        if multirest is not None:
            issue.fixes.append(Fix(multirest.id, {"count": measure.length + count}))
        else:
            issue.action = {"set_multirest": measure.length + count, "measure_id": measure.id}
        issue.symbol_ids = [multirest.id] if multirest else [s.id for s in measure.events]
        issue.measure_numbers = [measure.number]
        break
    return issue


def _extra_issue(ref: PartRef, extra: list[Unit], usual: int, confidence: float) -> Issue:
    measures = list({id(u.measure): u.measure for u in extra}.values())
    issue = Issue(code="part_measures_extra", part_id=ref.label,
                  measure_numbers=[m.number for m in measures], severity="error",
                  confidence=confidence, details={"extra": len(extra), "usual_length": usual})
    # Toutes les mesures en trop dans une même pause multiple : son nombre est trop grand.
    if len(measures) == 1 and measures[0].length > len(extra):
        multirest = next((s for s in measures[0].attributes if s.kind == "multirest"), None)
        if multirest is not None:
            issue.fixes.append(Fix(multirest.id, {"count": measures[0].length - len(extra)}))
            issue.symbol_ids = [multirest.id]
    return issue


def _time_disagreements(refs: list[PartRef], sequences: list[list[Unit]], reference: int,
                        alignments: dict) -> list[Issue]:
    """Chiffrages : à chaque mesure de la référence, que disent les parties ? Celles qui
    s'écartent d'une nette majorité sont signalées."""
    # aligned[j] = {partie: unité} pour chaque unité j de la référence.
    aligned: list[dict[int, Unit]] = [{reference: u} for u in sequences[reference]]
    for k, pairs in alignments.items():
        for mine, theirs in pairs:
            if mine is not None and theirs is not None:
                aligned[theirs][k] = sequences[k][mine]
    issues = []
    for position in aligned:
        votes = Counter(u.time for u in position.values())
        value, count = votes.most_common(1)[0]
        if len(position) < 3 or count <= len(position) / 2 or len(votes) == 1:
            continue
        for k, unit in position.items():
            if unit.time == value:
                continue
            time = next((s for s in unit.measure.attributes if s.kind == "time"), None)
            issue = Issue(code="part_time_signature_differs", part_id=refs[k].label,
                          measure_numbers=[unit.measure.number], severity="error",
                          confidence=round(count / len(position), 2),
                          details={"read": unit.time, "others": value,
                                   "agreeing_parts": count, "parts": len(position),
                                   "ref_index": k})
            if value is not None and time is not None:
                beats, beat_type = value.split("/")
                issue.fixes.append(Fix(time.id, {"beats": int(beats), "beat_type": int(beat_type)}))
                issue.symbol_ids = [time.id]
            elif value is not None:
                issue.action = {"insert_time": value, "before_measure": unit.measure.number}
            issues.append(issue)
    return issues
