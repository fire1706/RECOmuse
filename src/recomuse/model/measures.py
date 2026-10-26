"""Changer le découpage en mesures : réunir deux mesures, couper une mesure en deux.

La lecture se trompe parfois de barres de mesure : elle en voit une là où il n'y en a pas
(une hampe, un trait de soufflet pris pour une barre : deux mesures au lieu d'une), ou en
manque une (une seule mesure qui en contient deux). Ces deux gestes corrigent cela.

Ce module CALCULE le changement (quelles mesures disparaissent, lesquelles les
remplacent) sans rien modifier : c'est le service de corrections (learning/corrections.py,
« restructure ») qui l'applique et l'inscrit au journal, pour qu'il puisse être annulé et
retenu comme toute correction.
"""

from copy import deepcopy
from dataclasses import dataclass, replace

from recomuse.model.score import Measure, Part, ScoreModel


class MeasureEditError(ValueError):
    """Changement impossible ; `code` est traduit par l'interface."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass
class Restructure:
    """Remplacer `old` (mesures qui se suivent dans la partie `part_id`, à partir du rang
    `index`) par `new`."""

    part_id: str
    index: int
    old: list[Measure]
    new: list[Measure]
    selected: str            # mesure à montrer après le changement


def merge_with_next(model: ScoreModel, measure_id: str) -> Restructure:
    """Réunit une mesure et la suivante (barre de mesure en trop)."""
    part, index = _locate(model, measure_id)
    if index + 1 >= len(part.measures):
        raise MeasureEditError("no_next_measure")
    first, second = part.measures[index], part.measures[index + 1]
    if any(s.kind == "multirest" for m in (first, second) for s in m.attributes):
        raise MeasureEditError("merge_multirest")
    kinds = {s.kind for s in first.attributes}
    if any(s.kind in kinds for s in second.attributes):
        # Deux clés (ou deux chiffrages...) dans une même mesure : ce n'est pas une barre
        # en trop, mais un vrai changement.
        raise MeasureEditError("merge_conflict")
    merged = replace(
        deepcopy(first),
        bbox=_union(first, second),
        attributes=deepcopy(first.attributes + second.attributes),
        events=deepcopy(first.events + second.events),
        marks=first.marks + [m for m in second.marks if m not in first.marks],
    )
    return Restructure(part.id, index, [first, second], [merged], merged.id)


def split_after(model: ScoreModel, symbol_id: str) -> Restructure:
    """Coupe une mesure juste après une note ou un silence (barre de mesure manquée).
    Une note d'accord reste avec son accord."""
    try:
        part, measure, symbol = model.find(symbol_id)
    except KeyError:
        raise MeasureEditError("symbol_not_found", symbol_id) from None
    if symbol not in measure.events:
        raise MeasureEditError("split_not_an_event")
    if len({e.value.get("voice") or 1 for e in measure.events}) > 1:
        raise MeasureEditError("split_voices")
    cut = measure.events.index(symbol) + 1
    while cut < len(measure.events) and measure.events[cut].value.get("chord"):
        cut += 1
    if cut >= len(measure.events):
        raise MeasureEditError("split_at_end")
    index = part.measures.index(measure)
    left_box, right_box = _cut_box(measure, measure.events[cut])
    first = replace(deepcopy(measure), bbox=left_box, events=deepcopy(measure.events[:cut]))
    second = Measure(id=_new_id(model, measure.id), number=measure.number + 1,
                     page=measure.page, system=measure.system, bbox=right_box,
                     events=deepcopy(measure.events[cut:]),
                     expected_duration=measure.expected_duration)
    return Restructure(part.id, index, [measure], [first, second], second.id)


def _locate(model: ScoreModel, measure_id: str) -> tuple[Part, int]:
    try:
        part, measure = model.find_measure(measure_id)
    except KeyError:
        raise MeasureEditError("measure_not_found", measure_id) from None
    return part, part.measures.index(measure)


def _union(first: Measure, second: Measure):
    """Boîte des deux mesures réunies (si elles sont sur la même ligne de la même page)."""
    a, b = first.bbox, second.bbox
    if a is None or b is None or (first.page, first.system) != (second.page, second.system):
        return a or b
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _cut_box(measure: Measure, first_after):
    """Boîtes des deux moitiés : coupée juste avant la première note de la 2e mesure."""
    box = measure.bbox
    if box is None or first_after.bbox is None or not box[0] < first_after.bbox[0] \
            < box[0] + box[2]:
        return box, box
    x = first_after.bbox[0] - 4
    return (box[0], box[1], x - box[0], box[3]), (x, box[1], box[0] + box[2] - x, box[3])


def _new_id(model: ScoreModel, base: str) -> str:
    """Identifiant libre pour une mesure créée par une coupure."""
    taken = {m.id for p in model.parts for m in p.measures}
    k = 0
    while f"{base}+{k}" in taken:
        k += 1
    return f"{base}+{k}"
