"""Contrôle des durées : chaque mesure doit durer ce qu'annonce son chiffrage.

Trois cas :
- une mesure isolée de durée fausse : un symbole y est mal lu (note, point, triolet...) ;
- plusieurs mesures de suite qui ont TOUTES la même durée fausse : c'est presque sûrement
  un changement de chiffrage manqué (erreur constatée au test de faisabilité : 82 mesures
  fausses dans Green Hill, presque toutes pour cette raison) ; on propose le chiffrage qui
  correspond à la durée lue. Si la mesure qui suit la série a de nouveau la bonne durée,
  c'est un passage dans un autre chiffrage (un 2/4 au milieu d'un 4/4) : la correction
  proposée remet aussi l'ancien chiffrage après le passage, sinon les mesures suivantes,
  justes, deviendraient toutes fausses (erreurs en cascade) ; deux mesures suffisent alors ;
- une partie sans aucun chiffrage : on propose celui de la durée la plus fréquente ;
- deux mesures voisines trop courtes dont les durées font exactement une mesure : une barre
  de mesure en trop (une hampe prise pour une barre) ; une mesure qui en vaut exactement
  deux, avec un endroit où la première moitié est complète : une barre manquée. On propose
  de réunir les deux mesures, ou de couper la mesure (model/measures.py) ;
- une mesure vide (ni note, ni silence, ni pause multiple) : une mesure écrite n'est jamais
  vide, la lecture a manqué son contenu (vu sur une partie de tuba : des rondes graves,
  avec beaucoup de lignes supplémentaires, ignorées par Audiveris).
Une première mesure plus courte est une levée : elle est normale.
"""

from collections import Counter
from fractions import Fraction

from recomuse.model.score import Measure, Part, ScoreModel
from recomuse.validation.issues import Fix, Issue

# Nombre minimal de mesures de suite, de même durée fausse, pour conclure à un chiffrage manqué.
MIN_RUN = 3
# ... quand la mesure qui suit la série a de nouveau la bonne durée (passage délimité).
MIN_SECTION_RUN = 2


def meter_of(duration: Fraction) -> str:
    """Chiffrage qui correspond à une durée en noires : 3 → « 3/4 », 3/2 → « 3/8 »."""
    for beat_type in (4, 8, 16):
        beats = duration * beat_type / 4
        if beats.denominator == 1 and beats > 0:
            return f"{beats}/{beat_type}"
    return str(duration)


def _checkable(measure: Measure) -> bool:
    """Une mesure dont on peut contrôler la durée (pas une pause, ni vide)."""
    if any(s.kind == "multirest" for s in measure.attributes) or not measure.events:
        return False
    return not all(s.kind == "rest" and s.value.get("full_measure") for s in measure.events)


def _percussion_measures(part: Part) -> set[str]:
    """Mesures d'une portée de percussions (non contrôlées pour l'instant)."""
    result = set()
    percussion = False
    for measure in part.measures:
        for symbol in measure.attributes:
            if symbol.kind == "clef":
                percussion = symbol.value.get("sign") == "percussion"
        if percussion:
            result.add(measure.id)
    return result


def check_durations(model: ScoreModel) -> list[Issue]:
    issues: list[Issue] = []
    for part in model.parts:
        issues += _check_part(part)
        issues += _empty_measures(part)
    return issues


def _empty_measures(part: Part) -> list[Issue]:
    """Mesures sans rien dedans (ni note, ni silence, ni pause multiple). Pas celles des
    percussions : leur notation n'est pas encore lue."""
    skip = _percussion_measures(part)
    return [Issue(code="measure_empty", part_id=part.id, measure_numbers=[m.number],
                  severity="error", confidence=0.9,
                  details={"measure_id": m.id, "expected": m.expected_duration})
            for m in part.measures
            if m.id not in skip and not m.events
            and not any(s.kind == "multirest" for s in m.attributes)]


def _check_part(part: Part) -> list[Issue]:
    skip = _percussion_measures(part)
    measures = [m for m in part.measures if m.id not in skip]
    if not any(s.kind == "time" for m in measures for s in m.attributes):
        return _missing_time(part, measures)

    # Mesures fausses : (rang dans la partie, mesure, durée de la voix 1).
    wrong: list[tuple[int, Measure, Fraction]] = []
    for index, measure in enumerate(measures):
        if not _checkable(measure) or measure.expected_duration is None:
            continue
        expected = Fraction(measure.expected_duration)
        durations = {v: measure.duration(v) for v in _voices(measure)}
        if any(d is None for d in durations.values()):
            continue
        first = durations.get(1, next(iter(durations.values())))
        if all(d == expected for d in durations.values()):
            continue
        if index == 0 and first < expected and _next_is_right(measures):
            continue   # levée
        wrong.append((index, measure, first))

    issues = []
    used: set[str] = set()
    # Suites de mesures consécutives de même durée fausse → chiffrage manqué.
    start = 0
    while start < len(wrong):
        end = start
        while (end + 1 < len(wrong) and wrong[end + 1][0] == wrong[end][0] + 1
               and wrong[end + 1][2] == wrong[start][2]):
            end += 1
        run = wrong[start:end + 1]
        after = _right_after(measures, run[-1][0])
        if len(run) >= (MIN_SECTION_RUN if after is not None else MIN_RUN):
            issues.append(_missed_time(part, run, after))
            used.update(m.id for _, m, _ in run)
        start = end + 1

    # Barres de mesure en trop ou manquées. Une paire « 2 + 2 » en 4/4 peut aussi être un
    # passage à 2/4 : les deux questions restent (le chiffrage est demandé d'abord).
    structural = _bar_issues(part, measures, wrong)
    issues += structural
    used.update(i.details["measure_id"] for i in structural)
    used.update(i.details["next_id"] for i in structural if "next_id" in i.details)

    for _, measure, duration in wrong:
        if measure.id in used:
            continue
        issues.append(Issue(
            code="measure_duration", part_id=part.id, measure_numbers=[measure.number],
            severity="error", confidence=0.7,
            symbol_ids=[s.id for s in measure.events],
            details={"read": str(duration), "expected": measure.expected_duration},
        ))
    return issues


def _bar_issues(part: Part, measures: list[Measure],
                wrong: list[tuple[int, Measure, Fraction]]) -> list[Issue]:
    """Barre de mesure en trop (deux mesures à réunir) ou manquée (une mesure à couper)."""
    issues = []
    by_index = {index: (measure, duration) for index, measure, duration in wrong}
    taken: set[int] = set()
    for index, (measure, duration) in sorted(by_index.items()):
        if index in taken or len(_voices(measure)) > 1:
            continue
        expected = Fraction(measure.expected_duration)
        following = by_index.get(index + 1)
        if (following is not None and len(_voices(following[0])) == 1
                and following[0].expected_duration == measure.expected_duration
                and duration < expected and following[1] < expected
                and duration + following[1] == expected):
            issues.append(Issue(
                code="measures_merge_suspicious", part_id=part.id,
                measure_numbers=[measure.number, following[0].number], severity="error",
                confidence=0.6, symbol_ids=[],
                details={"measure_id": measure.id, "next_id": following[0].id,
                         "read": [str(duration), str(following[1])],
                         "expected": measure.expected_duration}))
            taken |= {index, index + 1}
            continue
        cut = _half_point(measure, expected) if duration == 2 * expected else None
        if cut is not None:
            issues.append(Issue(
                code="measure_split_suspicious", part_id=part.id,
                measure_numbers=[measure.number], severity="error", confidence=0.6,
                symbol_ids=[cut.id],
                details={"measure_id": measure.id, "after_id": cut.id,
                         "expected": measure.expected_duration}))
            taken.add(index)
    return issues


def _half_point(measure: Measure, expected: Fraction):
    """Note après laquelle la mesure a exactement la durée attendue (première moitié d'une
    mesure qui en vaut deux), ou None."""
    total = Fraction(0)
    for event in measure.events:
        if event.value.get("chord") or event.value.get("grace"):
            continue
        total += event.duration or Fraction(0)
        if total == expected:
            return event
        if total > expected:
            return None
    return None


def _next_is_right(measures: list[Measure]) -> bool:
    """Une 1re mesure courte n'est une levée que si la suivante a la bonne durée (sinon,
    c'est tout le morceau qui n'a pas le chiffrage lu)."""
    following = next((m for m in measures[1:] if _checkable(m)), None)
    if following is None or following.expected_duration is None:
        return True
    return following.duration() == Fraction(following.expected_duration)


def _voices(measure: Measure) -> set[int]:
    return {s.value.get("voice", 1) for s in measure.events} or {1}


def _right_after(measures: list[Measure], index: int) -> Measure | None:
    """La mesure qui suit `index`, si elle a la durée de son chiffrage (et n'en écrit pas
    un nouveau) : la série de mesures fausses est alors un passage délimité."""
    if index + 1 >= len(measures):
        return None
    after = measures[index + 1]
    if (not _checkable(after) or after.expected_duration is None
            or any(s.kind == "time" for s in after.attributes)):
        return None
    return after if after.duration() == Fraction(after.expected_duration) else None


def _time_in_force(part: Part, measure: Measure) -> dict | None:
    """Valeur du chiffrage en vigueur dans la mesure (écrit dans elle, ou avant)."""
    current = None
    for m in part.measures:
        current = next((dict(s.value) for s in m.attributes if s.kind == "time"), current)
        if m is measure:
            break
    return current


def _missed_time(part: Part, run: list[tuple[int, Measure, Fraction]],
                 after: Measure | None = None) -> Issue:
    first = run[0][1]
    duration = run[0][2]
    meter = meter_of(duration)
    beats, beat_type = (int(v) for v in meter.split("/"))
    issue = Issue(
        code="time_signature_missed", part_id=part.id,
        measure_numbers=[m.number for _, m, _ in run], severity="error",
        confidence=min(0.95, 0.6 + 0.05 * len(run)),
        details={"read_duration": str(duration), "expected": first.expected_duration,
                 "proposed": meter},
    )
    previous = _time_in_force(part, first)
    existing = next((s for s in first.attributes if s.kind == "time"), None)
    if existing is not None:
        # Le chiffrage est bien lu à cet endroit, mais faux : on propose de le changer.
        issue.fixes.append(Fix(existing.id, {"beats": beats, "beat_type": beat_type}))
    else:
        issue.action = {"insert_time": meter, "before_measure": first.number}
    if after is not None and previous is not None:
        # Passage délimité : l'ancien chiffrage revient à la mesure qui suit.
        issue.action |= {"restore_time": previous, "restore_measure_id": after.id}
        issue.details |= {"back": f"{previous['beats']}/{previous['beat_type']}",
                          "last_measure": run[-1][1].number}
    return issue


def _missing_time(part: Part, measures: list[Measure]) -> list[Issue]:
    """Partie sans chiffrage : on propose celui de la durée la plus fréquente, seulement si
    au moins MIN_RUN mesures le confirment (sur une ou deux mesures, ce serait un hasard)."""
    durations = Counter(m.duration() for m in measures
                        if _checkable(m) and m.duration() is not None)
    if not durations:
        return []
    duration, count = durations.most_common(1)[0]
    issue = Issue(code="time_signature_missing", part_id=part.id,
                  measure_numbers=[measures[0].number], severity="error", confidence=0.3,
                  details={"proposed": None, "measures_matching": count})
    if count >= MIN_RUN:
        share = count / sum(durations.values())
        issue.confidence = round(min(0.9, share * min(1.0, count / 6)), 2)
        issue.details["proposed"] = meter_of(duration)
        issue.action = {"insert_time": meter_of(duration), "before_measure": measures[0].number}
    return [issue]
