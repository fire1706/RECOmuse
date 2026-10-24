"""Des doutes du validateur aux questions posées au musicien.

Chaque problème du validateur qui propose une correction devient une question : un
extrait de la partition (la zone de la page, le symbole entouré) et des choix cliquables.
Les problèmes sans proposition (une mesure dont le compte est faux, sans explication)
ne deviennent pas des questions : ils seront à revoir dans la vue côte à côte (tâche 9).
Les problèmes trouvés en comparant les parties d'un même morceau (validation/comparison.py)
en sont aussi : « les autres parties ont 7 mesures de plus ici : cette pause dure-t-elle
8 mesures ? ».

Les textes ne sont PAS écrits ici : une question porte un code (« multirest_missed ») et
des valeurs (« count » : 8), un choix porte une étiquette (« rest_measures ») ; l'interface
les traduit (ui/src/locales).

Ordre des questions : d'abord celles dont la réponse peut corriger beaucoup de mesures
(clé octaviée, chiffrage, pauses multiples), puis les notes ; à l'intérieur, dans l'ordre
de la partition.
Regroupement : une seule question pour plusieurs doutes de même cause. Les notes hors de
la tessiture d'une partie, toutes dans le même sens, sont une seule question (« ces 12
notes sont-elles une octave trop haut ? »). Deux problèmes qui proposent de changer la
même pause (pause multiple manquée, numéros de mesure imprimés) sont une seule question.
"""

from dataclasses import dataclass, field
from typing import Any

from recomuse.learning.corrections import NewSymbol
from recomuse.learning.rules import issue_signature
from recomuse.model.score import Measure, Part, ScoreModel, Symbol
from recomuse.validation.issues import Fix, Issue, ValidationReport

# Ordre de priorité des types de questions.
CODE_ORDER = [
    "clef_octave_suspicious",
    "time_signature_missing",
    "time_signature_missed",
    "part_time_signature_differs",
    "multirest_missed",
    "measure_number_mismatch",
    "part_measures_missing",
    "part_measures_extra",
    "multirest_count_unknown",
    "note_out_of_range",
    "note_position_mismatch",
]

# Zone montrée autour du doute : marge (pixels de l'image à 300 dpi) autour des symboles
# et de la mesure concernés, et nombre maximal de symboles entourés.
REGION_MARGIN = 40
MAX_HIGHLIGHTS = 8

Box = tuple[float, float, float, float]   # x, y, largeur, hauteur


@dataclass
class Choice:
    """Une réponse possible."""

    id: str                                   # « accept », « keep », « count »
    label: str                                # étiquette traduite par l'interface
    params: dict[str, Any] = field(default_factory=dict)   # valeurs affichées
    fixes: list[Fix] = field(default_factory=list)
    additions: list[NewSymbol] = field(default_factory=list)
    # Choix où l'utilisateur tape un nombre (« count » : nombre de mesures d'une pause) :
    # la mesure à changer, et sa pause multiple si elle en a déjà une.
    input: str | None = None
    measure_id: str | None = None
    multirest_id: str | None = None

    def changes(self, value: int | None = None) -> tuple[list[Fix], list[NewSymbol]]:
        """Corrections à appliquer si l'utilisateur choisit cette réponse."""
        if self.input == "count":
            if not isinstance(value, int) or value < 1:
                raise ValueError("Le nombre de mesures doit être un entier positif.")
            return _multirest_changes(self.measure_id, self.multirest_id, value)
        return list(self.fixes), list(self.additions)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "params": self.params, "input": self.input}


@dataclass
class Question:
    """Une question à poser."""

    key: str                                  # identifiant stable (voir _key)
    code: str                                 # type de doute (code du validateur)
    part_id: str
    measure_numbers: list[int]
    page: int | None
    measure_id: str | None                    # mesure concernée (pour la vue côte à côte)
    region: Box | None                        # zone de la page à montrer
    highlights: list[Box]                     # symboles à entourer dans cette zone
    params: dict[str, Any]
    choices: list[Choice]
    confidence: float
    issue_count: int = 1                      # doutes réglés par cette seule question
    # Type de doute et ce qui le caractérise (learning/rules.py) : la réponse donnée
    # nourrit les règles apprises ; une règle apprise peut y répondre seule.
    signature: dict[str, Any] | None = None

    def choice(self, choice_id: str) -> Choice:
        for choice in self.choices:
            if choice.id == choice_id:
                return choice
        raise KeyError(choice_id)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "code": self.code, "part_id": self.part_id,
            "measure_numbers": self.measure_numbers, "page": self.page,
            "measure_id": self.measure_id,
            "params": self.params, "choices": [c.to_dict() for c in self.choices],
            "confidence": self.confidence, "issue_count": self.issue_count,
        }


def build_questions(model: ScoreModel,
                    report: ValidationReport) -> tuple[list[Question], list[Issue]]:
    """Questions à poser pour ce rapport, dans l'ordre où les poser. Renvoie aussi les
    problèmes qui ne deviennent pas des questions (passages à vérifier à l'œil)."""
    questions: dict[str, Question] = {}
    unasked: list[Issue] = []
    out_of_range: dict[tuple[str, str], list[Issue]] = {}
    for issue in report.issues:
        if issue.code == "note_out_of_range" and issue.fixes:
            out_of_range.setdefault((issue.part_id, issue.details.get("direction")),
                                    []).append(issue)
            continue
        builder = BUILDERS.get(issue.code)
        question = builder(model, issue) if builder else None
        if question is not None:
            question.signature = issue_signature(model, issue)
        if question is None:
            unasked.append(issue)
        elif question.key in questions:
            # Même pause, autre indice : une seule question, celle du type le plus parlant.
            kept = questions[question.key]
            if _rank(question.code) < _rank(kept.code):
                question.issue_count += kept.issue_count
                questions[question.key] = question
            else:
                kept.issue_count += 1
        else:
            questions[question.key] = question
    for issues in out_of_range.values():
        question = _out_of_range(model, issues)
        question.signature = issue_signature(model, issues[0])
        questions[question.key] = question

    ordered = sorted(questions.values(), key=lambda q: (
        _rank(q.code), q.part_id, q.measure_numbers[0] if q.measure_numbers else 0))
    return ordered, unasked


def check_items(model: ScoreModel, issues: list[Issue]) -> list[dict]:
    """Passages à vérifier à l'œil (problèmes sans question), dans l'ordre de la
    partition : de quoi les montrer dans la vue côte à côte."""
    items = []
    for issue in issues:
        _, measure = _part_and_measure(model, issue)
        details = {k: v for k, v in issue.details.items()
                   if isinstance(v, str | int | float) and k not in ("ref_index", "measure_id")}
        items.append({"code": issue.code, "measure_numbers": list(issue.measure_numbers),
                      "measure_id": measure.id if measure else None,
                      "page": measure.page if measure else None, "details": details})
    return sorted(items, key=lambda i: i["measure_numbers"][0] if i["measure_numbers"] else 0)


def _rank(code: str) -> int:
    """Rang d'un type de question dans l'ordre où les poser."""
    return CODE_ORDER.index(code) if code in CODE_ORDER else len(CODE_ORDER)


# --- Une fonction par type de doute ---------------------------------------------------------


def _clef_octave(model: ScoreModel, issue: Issue) -> Question | None:
    """Clé lue « octaviée » (petit 8 en dessous) : toute la partie serait une octave trop
    bas. Le musicien voit la clé et dit si le petit 8 y est."""
    if not issue.fixes:
        return None
    clef = _symbol(model, issue.fixes[0].symbol_id)
    change = issue.details.get("octave_change")
    return _question(model, issue, [clef] if clef else [],
                     params={"octave_change": change, "notes": issue.details.get("notes")},
                     choices=[Choice("accept", "clef_plain", fixes=list(issue.fixes)),
                              Choice("keep", "clef_octave", {"octave_change": change})])


def _note_position(model: ScoreModel, issue: Issue) -> Question | None:
    """Hauteur lue différente de celle que donne la position de la tête sur la portée."""
    if not issue.fixes:
        return None
    note = _symbol(model, issue.fixes[0].symbol_id)
    if note is None:
        return None
    read = _note_params(note.value)
    proposed = _note_params({**note.value, **issue.fixes[0].value})
    return _question(model, issue, [note], params={},
                     choices=[Choice("accept", "note", {"note": proposed},
                                     fixes=list(issue.fixes)),
                              Choice("keep", "note", {"note": read})])


def _out_of_range(model: ScoreModel, issues: list[Issue]) -> Question:
    """Notes trop hautes (ou trop basses) pour l'instrument : une octave de trop ?"""
    first = issues[0]
    fixes = [fix for issue in issues for fix in issue.fixes]
    notes = [s for s in (_symbol(model, f.symbol_id) for f in fixes) if s is not None]
    direction = first.details.get("direction")
    numbers = sorted({n for issue in issues for n in issue.measure_numbers})
    question = _question(
        model, first, notes,
        params={"count": len(fixes), "direction": direction,
                "instrument": first.details.get("instrument"),
                "notes": [_note_params(n.value) for n in notes[:MAX_HIGHLIGHTS]]},
        choices=[Choice("accept", "octave_down" if direction == "high" else "octave_up",
                        fixes=fixes),
                 Choice("keep", "notes_correct")],
        key=f"note_out_of_range:{first.part_id}:{direction}")
    question.measure_numbers = numbers
    question.issue_count = len(issues)
    return question


def _time_signature(model: ScoreModel, issue: Issue) -> Question | None:
    """Chiffrage manqué (plusieurs mesures de suite ont la même durée fausse), absent, ou
    différent de celui des autres parties du morceau au même endroit."""
    proposed = (issue.details.get("proposed") or issue.details.get("others")
                or issue.action.get("insert_time"))
    if not proposed:
        return None
    part, first = _part_and_measure(model, issue)
    if first is None:
        return None
    beats, beat_type = (int(n) for n in proposed.split("/"))
    value = {"beats": beats, "beat_type": beat_type}
    if issue.fixes:
        accept = Choice("accept", "time_is", {"time": proposed}, fixes=list(issue.fixes))
    else:
        target = _measure_at(part, issue.action.get("before_measure", first.number)) or first
        accept = Choice("accept", "time_is", {"time": proposed},
                        additions=[NewSymbol(target.id, "time", value)])
    choices = [accept]
    params = {"time": proposed, "measures": len(issue.measure_numbers)}
    if issue.code == "time_signature_missed":
        read = _time_text(model, part, first)
        choices.append(Choice("keep", "time_unchanged", {"time": read}))
    elif issue.code == "part_time_signature_differs":
        read = issue.details.get("read")
        choices.append(Choice("keep", "time_as_read", {"time": read}) if read
                       else Choice("keep", "time_unchanged"))
        params = {"time": proposed, "agreeing_parts": issue.details.get("agreeing_parts"),
                  "parts": issue.details.get("parts")}
    return _question(model, issue, [], params=params, choices=choices)


def _multirest(model: ScoreModel, issue: Issue) -> Question | None:
    """Pause multiple manquée, nombre mal lu ou inconnu, ou numéros de mesure imprimés qui
    sautent : combien de mesures dure ce silence ?"""
    measure = _target_measure(model, issue)
    if measure is None:
        return None
    multirest = next((s for s in measure.attributes if s.kind == "multirest"), None)
    count = issue.action.get("set_multirest") or issue.details.get("count")
    if issue.fixes and "count" in issue.fixes[0].value:
        count = issue.fixes[0].value["count"]
    if issue.code == "multirest_count_unknown":
        count = None
    elif issue.code in NEEDS_PROPOSAL and not (issue.action or issue.fixes):
        return None            # écart sans pause pour l'expliquer
    choices = []
    if count and (count > 1 or multirest is not None):
        fixes, additions = _multirest_changes(measure.id, multirest.id if multirest else None,
                                              count)
        choices.append(Choice("accept", "rest_measures", {"count": count}, fixes=fixes,
                              additions=additions))
    choices.append(Choice("count", "rest_other_count", input="count", measure_id=measure.id,
                          multirest_id=multirest.id if multirest else None))
    if multirest is None:
        choices.append(Choice("keep", "rest_one_measure"))
    elif issue.code in NEEDS_PROPOSAL:
        # Les autres parties peuvent se tromper aussi : garder le nombre lu.
        choices.append(Choice("keep", "rest_as_read", {"count": measure.length}))
    params = {"count": count}
    if issue.code == "measure_number_mismatch":
        params |= {"printed_before": issue.details.get("printed_before"),
                   "printed_after": issue.details.get("printed_after")}
    elif issue.code in ("part_measures_missing", "part_measures_extra"):
        params |= {"difference": issue.details.get("missing") or issue.details.get("extra"),
                   "read": measure.length}
    symbols = [multirest] if multirest else list(measure.events)
    question = _question(model, issue, symbols, params=params, choices=choices,
                         key=f"multirest:{issue.part_id}:{measure.id}", measure=measure)
    question.measure_numbers = [measure.number]
    return question


# Doutes qui ne deviennent une question que s'ils proposent une pause à corriger.
NEEDS_PROPOSAL = ("measure_number_mismatch", "part_measures_missing", "part_measures_extra")

BUILDERS = {
    "clef_octave_suspicious": _clef_octave,
    "note_position_mismatch": _note_position,
    "time_signature_missed": _time_signature,
    "time_signature_missing": _time_signature,
    "multirest_missed": _multirest,
    "multirest_count_unknown": _multirest,
    "measure_number_mismatch": _multirest,
    "part_measures_missing": _multirest,
    "part_measures_extra": _multirest,
    "part_time_signature_differs": _time_signature,
}


# --- Outils ---------------------------------------------------------------------------------


def _question(model: ScoreModel, issue: Issue, symbols: list[Symbol], params: dict,
              choices: list[Choice], key: str | None = None,
              measure: Measure | None = None) -> Question:
    """Assemble une question : zone de la page à montrer, symboles à entourer."""
    if measure is None:
        _, measure = _part_and_measure(model, issue)
    page = next((s.page for s in symbols if s.page is not None and s.bbox is not None),
                measure.page if measure else None)
    highlights = [s.bbox for s in symbols if s.bbox is not None and s.page == page]
    highlights = highlights[:MAX_HIGHLIGHTS]
    boxes = list(highlights)
    if measure is not None and measure.bbox is not None and measure.page == page:
        boxes.append(measure.bbox)
    region = _union(boxes, REGION_MARGIN) if boxes else None
    return Question(key=key or _key(model, issue), code=issue.code, part_id=issue.part_id,
                    measure_numbers=list(issue.measure_numbers), page=page,
                    measure_id=measure.id if measure else None, region=region,
                    highlights=highlights, params=params, choices=choices,
                    confidence=issue.confidence)


def _key(model: ScoreModel, issue: Issue) -> str:
    """Identifiant stable d'une question : le type de doute et les symboles concernés, ou
    à défaut les identifiants des mesures (leurs numéros, eux, changent quand une pause
    multiple est corrigée)."""
    targets = sorted({f.symbol_id for f in issue.fixes} | set(issue.symbol_ids))
    if not targets:
        part = _part(model, issue.part_id)
        measures = [_measure_at(part, n) for n in issue.measure_numbers]
        targets = [m.id if m else str(n) for m, n in zip(measures, issue.measure_numbers,
                                                         strict=True)]
    return f"{issue.code}:{issue.part_id}:{','.join(targets)}"


def _multirest_changes(measure_id: str | None, multirest_id: str | None,
                       count: int) -> tuple[list[Fix], list[NewSymbol]]:
    """Faire durer `count` mesures un silence : changer le nombre de sa pause multiple, ou
    en ajouter une (count = 1 : une mesure simple, il n'y a rien à ajouter)."""
    if multirest_id is not None:
        return [Fix(multirest_id, {"count": count})], []
    if count == 1 or measure_id is None:
        return [], []
    return [], [NewSymbol(measure_id, "multirest", {"count": count})]


def _symbol(model: ScoreModel, symbol_id: str) -> Symbol | None:
    try:
        return model.find(symbol_id)[2]
    except KeyError:
        return None


def _part(model: ScoreModel, part_id: str) -> Part | None:
    return next((p for p in model.parts if p.id == part_id), None)


def _measure_at(part: Part | None, number: int) -> Measure | None:
    """Mesure de la partie qui porte ce numéro (une pause multiple en couvre plusieurs)."""
    if part is None:
        return None
    return next((m for m in part.measures if m.number <= number < m.number + m.length), None)


def _part_and_measure(model: ScoreModel, issue: Issue) -> tuple[Part | None, Measure | None]:
    """Partie et première mesure concernées par un problème."""
    for symbol_id in [f.symbol_id for f in issue.fixes] + issue.symbol_ids:
        try:
            part, measure, _ = model.find(symbol_id)
            return part, measure
        except KeyError:
            continue
    part = _part(model, issue.part_id)
    number = issue.measure_numbers[0] if issue.measure_numbers else None
    return part, _measure_at(part, number) if number is not None else None


def _target_measure(model: ScoreModel, issue: Issue) -> Measure | None:
    """Mesure de silence dont il faut changer la durée."""
    measure_id = issue.action.get("measure_id")
    if measure_id:
        try:
            return model.find_measure(measure_id)[1]
        except KeyError:
            return None
    return _part_and_measure(model, issue)[1]


def _time_text(model: ScoreModel, part: Part | None, measure: Measure) -> str | None:
    """Chiffrage en vigueur dans une mesure (le dernier écrit avant elle, ou en elle)."""
    current = None
    for m in part.measures if part else []:
        for symbol in m.attributes:
            if symbol.kind == "time":
                current = f"{symbol.value['beats']}/{symbol.value['beat_type']}"
        if m is measure:
            break
    return current


def _note_params(value: dict) -> dict:
    """Ce qu'il faut à l'interface pour écrire le nom d'une note (do♯5, C♯5)."""
    return {"step": value.get("step"), "octave": value.get("octave"),
            "alter": value.get("alter") or 0}


def _union(boxes: list[Box], margin: float) -> Box:
    x0 = min(b[0] for b in boxes) - margin
    y0 = min(b[1] for b in boxes) - margin
    x1 = max(b[0] + b[2] for b in boxes) + margin
    y1 = max(b[1] + b[3] for b in boxes) + margin
    return (max(0.0, x0), max(0.0, y0), x1 - max(0.0, x0), y1 - max(0.0, y0))
