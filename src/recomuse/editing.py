"""Édition manuelle : les gestes du musicien dans la vue côte à côte, traduits en corrections.

Chaque geste (« cette note un cran plus haut », « cette mesure est en 3/4 », « supprimer
cette note ») devient une ou plusieurs corrections du service de corrections (source
« manual »), enregistrées ensemble : « annuler ma dernière modification » les défait
toutes d'un coup.

Certains gestes en entraînent d'autres, comme le ferait un musicien :
- changer l'armure change l'altération des notes qui suivaient l'ancienne armure ;
- changer la clé déplace les notes qui suivent (elles restent à leur place sur la
  portée, c'est leur nom qui change) ;
- changer une durée garde le point et le nolet de la note.

Les gestes arrivent de l'interface sous la forme {"op": ..., ...} (voir apply_edit).
"""

import sqlite3
from fractions import Fraction
from typing import Any

from recomuse.learning.corrections import CorrectionError, CorrectionService, NewSymbol
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.score import Measure, Part, ScoreModel, Symbol, fraction_text
from recomuse.model.store import load_model
from recomuse.vector.pitch import (
    clef_bottom_line,
    degree,
    from_degree,
    key_alter,
    moved_by_clef,
)

# Durées écrites proposées (en noires) : ronde, blanche, noire, croche, double, triple.
WRITTEN_DURATIONS = ("4", "2", "1", "1/2", "1/4", "1/8")
# Note de référence de chaque clé (sur la ligne de la clé) : sol, fa, ut.


class EditError(ValueError):
    """Geste impossible (symbole inconnu, valeur hors des choix proposés...)."""


# --- Lecture d'une mesure -----------------------------------------------------------------


def measure_details(model: ScoreModel, measure_id: str) -> dict:
    """Tout ce que l'éditeur montre d'une mesure : ses réglages, ses notes et silences,
    ce qui est en vigueur (clé, armure, chiffrage), sa durée lue et attendue."""
    part, measure = _measure(model, measure_id)
    state = _state_at(part, measure)
    index = part.measures.index(measure)
    duration = measure.duration()
    return {
        "id": measure.id, "number": measure.number, "page": measure.page,
        "length": measure.length, "part_id": part.id,
        "duration": fraction_text(duration) if duration is not None else None,
        "expected": measure.expected_duration,
        "attributes": [_symbol_dict(s) for s in measure.attributes],
        "events": [_symbol_dict(s) for s in measure.events],
        "state": state,
        "previous": part.measures[index - 1].id if index > 0 else None,
        "next": part.measures[index + 1].id if index + 1 < len(part.measures) else None,
    }


def _symbol_dict(symbol: Symbol) -> dict:
    value = dict(symbol.value)
    if symbol.kind in ("note", "rest"):
        value["written"] = fraction_text(_written(symbol))
    return {"id": symbol.id, "kind": symbol.kind, "value": value,
            "confidence": symbol.confidence, "source": symbol.source}


# --- Gestes -------------------------------------------------------------------------------


def apply_edit(conn: sqlite3.Connection, service: CorrectionService, score_id: int,
               edit: dict[str, Any]) -> dict:
    """Applique un geste ; renvoie {"measure_id": mesure concernée, "symbol_id": symbole à
    garder choisi (le nouveau, après un ajout), "corrections": numéros dans le journal}."""
    model = _load(conn, score_id)
    op = edit.get("op")
    handler = OPERATIONS.get(op)
    if handler is None:
        raise EditError(f"Geste inconnu : {op}")
    changes, additions, removals, measure_id, selected = handler(model, edit)
    if not (changes or additions or removals):
        return {"measure_id": measure_id, "symbol_id": selected, "corrections": []}
    try:
        ids = service.apply_group(score_id, changes, source="manual", reason=f"edit:{op}",
                                  additions=additions, removals=removals)
    except CorrectionError as error:
        raise EditError(str(error)) from None
    if additions and selected is None:
        selected = CorrectionJournal(conn).get(ids[-1]).symbol_id
    return {"measure_id": measure_id, "symbol_id": selected, "corrections": ids}


def undo_last_edit(conn: sqlite3.Connection, service: CorrectionService,
                   score_id: int) -> str | None:
    """Annule la dernière modification manuelle (toutes ses corrections). Renvoie la mesure
    concernée, ou None s'il n'y a rien à annuler."""
    group = last_edit(conn, score_id)
    if not group:
        return None
    service.revert_all([c.id for c in group])
    first = group[0]
    if first.location:
        return first.location.get("measure_id")
    try:
        return _load(conn, score_id).find(first.symbol_id)[1].id
    except KeyError:
        return None


def last_edit(conn: sqlite3.Connection, score_id: int) -> list:
    """Corrections de la dernière modification manuelle encore en vigueur."""
    history = CorrectionJournal(conn).list_for_score(score_id)
    reverted = {c.reverts_id for c in history if c.source == "revert"}
    manual = [c for c in history if c.source == "manual" and c.id not in reverted]
    if not manual:
        return []
    last = manual[-1]
    if last.group_id is None:
        return [last]
    return [c for c in manual if c.group_id == last.group_id]


# Chaque geste renvoie (changements, ajouts, suppressions, mesure, symbole choisi).
Result = tuple[list, list, list, str | None, str | None]


def _set(model: ScoreModel, edit: dict) -> Result:
    """Changer directement des champs d'un symbole (ex. le nombre d'une pause multiple)."""
    symbol, measure = _symbol(model, edit)
    return [(symbol.id, dict(edit.get("value") or {}))], [], [], measure.id, symbol.id


def _pitch(model: ScoreModel, edit: dict) -> Result:
    """Note un cran plus haut ou plus bas (de do à ré...), avec l'altération de l'armure."""
    note, measure = _symbol(model, edit, "note")
    steps = int(edit.get("steps", 0))
    step, octave = from_degree(degree(note.value["step"], note.value["octave"]) + steps)
    fifths = _state_at(*_measure(model, measure.id))["fifths"]
    value = {"step": step, "octave": octave, "alter": key_alter(fifths, step)}
    return [(note.id, value)], [], [], measure.id, note.id


def _octave(model: ScoreModel, edit: dict) -> Result:
    note, measure = _symbol(model, edit, "note")
    change = int(edit.get("change", 0))
    return [(note.id, {"octave": note.value["octave"] + change})], [], [], measure.id, note.id


def _alter(model: ScoreModel, edit: dict) -> Result:
    note, measure = _symbol(model, edit, "note")
    alter = edit.get("alter")
    if alter not in (-2, -1, 0, 1, 2):
        raise EditError(f"Altération impossible : {alter}")
    return [(note.id, {"alter": alter})], [], [], measure.id, note.id


def _duration(model: ScoreModel, edit: dict) -> Result:
    """Nouvelle durée écrite (et nombre de points) : le nolet éventuel est gardé."""
    symbol, measure = _symbol(model, edit)
    if symbol.kind not in ("note", "rest"):
        raise EditError("Seules les notes et les silences ont une durée.")
    value = {"duration": fraction_text(_actual(symbol, edit)),
             "dots": int(edit.get("dots", symbol.value.get("dots") or 0))}
    if symbol.kind == "rest":
        value["full_measure"] = False
    return [(symbol.id, value)], [], [], measure.id, symbol.id


def _tie(model: ScoreModel, edit: dict) -> Result:
    """Lier (ou délier) la note à la suivante de même hauteur."""
    note, measure = _symbol(model, edit, "note")
    tied = not note.value.get("tie_start")
    changes = [(note.id, {"tie_start": tied})]
    following = _next_note(model, note)
    if following is not None:
        changes.append((following.id, {"tie_stop": tied}))
    return changes, [], [], measure.id, note.id


def _remove(model: ScoreModel, edit: dict) -> Result:
    symbol, measure = _symbol(model, edit)
    return [], [], [symbol.id], measure.id, None


def _add(kind: str):
    """Ajouter une note (ou un silence) après le symbole choisi, ou au début de la mesure."""
    def add(model: ScoreModel, edit: dict) -> Result:
        part, measure = _measure(model, edit.get("measure_id"))
        after = edit.get("after")
        model_after = next((s for s in measure.events if s.id == after), None)
        if after is not None and model_after is None:
            raise EditError(f"Symbole introuvable dans la mesure : {after}")
        template = model_after if model_after is not None and model_after.kind == kind else None
        written = Fraction(edit.get("written") or (fraction_text(_written(template))
                                                   if template else "1"))
        dots = int(edit.get("dots", 0))
        value: dict[str, Any] = {
            "duration": fraction_text(written * (2 - Fraction(1, 2 ** dots))),
            "dots": dots, "voice": (model_after.value.get("voice") if model_after else 1) or 1}
        if kind == "note":
            step, octave = _default_pitch(part, measure, template)
            fifths = _state_at(part, measure)["fifths"]
            value |= {"step": edit.get("step", step), "octave": edit.get("octave", octave),
                      "alter": key_alter(fifths, edit.get("step", step)), "chord": False,
                      "grace": False, "tie_start": False, "tie_stop": False}
        return [], [NewSymbol(measure.id, kind, value, after=after)], [], measure.id, None
    return add


def _time(model: ScoreModel, edit: dict) -> Result:
    """Chiffrage de la mesure (changé s'il y en a un, ajouté sinon)."""
    _, measure = _measure(model, edit.get("measure_id"))
    beats, beat_type = int(edit.get("beats", 0)), int(edit.get("beat_type", 0))
    if not 1 <= beats <= 32 or beat_type not in (1, 2, 4, 8, 16, 32):
        raise EditError(f"Chiffrage impossible : {beats}/{beat_type}")
    return _set_attribute(measure, "time", {"beats": beats, "beat_type": beat_type})


def _key(model: ScoreModel, edit: dict) -> Result:
    """Armure de la mesure. Les notes qui suivaient l'ancienne armure (jusqu'à la suivante)
    suivent la nouvelle : un si bémol par l'armure devient si naturel en passant à do."""
    part, measure = _measure(model, edit.get("measure_id"))
    fifths = int(edit.get("fifths", 99))
    if not -7 <= fifths <= 7:
        raise EditError(f"Armure impossible : {fifths}")
    old = _state_at(part, measure)["fifths"]
    changes, additions, removals, measure_id, selected = _set_attribute(
        measure, "key", {"fifths": fifths})
    for note in _notes_until(part, measure, "key"):
        step = note.value.get("step")
        if step and (note.value.get("alter") or 0) == key_alter(old, step):
            new = key_alter(fifths, step)
            if new != key_alter(old, step):
                changes.append((note.id, {"alter": new}))
    return changes, additions, removals, measure_id, selected


def _clef(model: ScoreModel, edit: dict) -> Result:
    """Clé de la mesure. Les notes qui suivent (jusqu'à la clé suivante) gardent leur place
    sur la portée : leur nom change d'autant que la clé (sol → fa : deux lignes et une
    octave plus bas)."""
    part, measure = _measure(model, edit.get("measure_id"))
    sign = edit.get("sign")
    if sign not in ("G", "F", "C", "percussion"):
        raise EditError(f"Clé impossible : {sign}")
    value = {"sign": sign, "line": None if sign == "percussion" else int(edit.get("line", 2)),
             "octave_change": int(edit.get("octave_change", 0))}
    old = _state_at(part, measure)["clef"]
    changes, additions, removals, measure_id, selected = _set_attribute(measure, "clef", value)
    shift = _bottom_line(value) - _bottom_line(old)
    fifths = _state_at(part, measure)["fifths"]
    if shift and sign != "percussion" and old.get("sign") != "percussion":
        for note in _notes_until(part, measure, "clef"):
            if not note.value.get("step"):
                continue
            changes.append((note.id, moved_by_clef(note.value, shift, fifths)))
    return changes, additions, removals, measure_id, selected


def _multirest(model: ScoreModel, edit: dict) -> Result:
    """Faire durer N mesures un silence (N = 1 : une mesure simple, la pause est retirée)."""
    _, measure = _measure(model, edit.get("measure_id"))
    count = int(edit.get("count", 0))
    if not 1 <= count <= 999:
        raise EditError(f"Nombre de mesures impossible : {count}")
    existing = next((s for s in measure.attributes if s.kind == "multirest"), None)
    if count == 1:
        return [], [], [existing.id] if existing else [], measure.id, None
    return _set_attribute(measure, "multirest", {"count": count})


OPERATIONS = {
    "set": _set, "pitch": _pitch, "octave": _octave, "alter": _alter,
    "duration": _duration, "tie": _tie, "remove": _remove,
    "add_note": _add("note"), "add_rest": _add("rest"),
    "time": _time, "key": _key, "clef": _clef, "multirest": _multirest,
}


# --- Outils -------------------------------------------------------------------------------


def _load(conn: sqlite3.Connection, score_id: int) -> ScoreModel:
    model = load_model(conn, score_id)
    if model is None:
        raise EditError(f"Aucune partition lue sous le n° {score_id}.")
    return model


def _measure(model: ScoreModel, measure_id: str | None) -> tuple[Part, Measure]:
    try:
        return model.find_measure(measure_id or "")
    except KeyError:
        raise EditError(f"Mesure introuvable : {measure_id}") from None


def _symbol(model: ScoreModel, edit: dict, kind: str | None = None) -> tuple[Symbol, Measure]:
    try:
        _, measure, symbol = model.find(edit.get("symbol_id") or "")
    except KeyError:
        raise EditError(f"Symbole introuvable : {edit.get('symbol_id')}") from None
    if kind is not None and symbol.kind != kind:
        raise EditError(f"Geste réservé aux symboles « {kind} ».")
    return symbol, measure


def _set_attribute(measure: Measure, kind: str, value: dict) -> Result:
    existing = next((s for s in measure.attributes if s.kind == kind), None)
    if existing is not None:
        return [(existing.id, value)], [], [], measure.id, existing.id
    return [], [NewSymbol(measure.id, kind, value)], [], measure.id, None


def _state_at(part: Part, measure: Measure) -> dict:
    """Clé, armure et chiffrage en vigueur dans la mesure (elle comprise)."""
    state = {"clef": {"sign": "G", "line": 2, "octave_change": 0}, "fifths": 0, "time": None}
    for m in part.measures:
        for symbol in m.attributes:
            if symbol.kind == "clef":
                state["clef"] = dict(symbol.value)
            elif symbol.kind == "key":
                state["fifths"] = symbol.value["fifths"]
            elif symbol.kind == "time":
                state["time"] = f"{symbol.value['beats']}/{symbol.value['beat_type']}"
        if m is measure:
            break
    return state


def _notes_until(part: Part, measure: Measure, kind: str):
    """Notes de la mesure et des suivantes, jusqu'au prochain symbole `kind` (exclu)."""
    start = part.measures.index(measure)
    for k, m in enumerate(part.measures[start:]):
        if k > 0 and any(s.kind == kind for s in m.attributes):
            return
        yield from (s for s in m.events if s.kind == "note")


def _bottom_line(clef: dict) -> int:
    """Degré (voir vector.pitch) de la note sur la ligne du bas avec cette clé."""
    return clef_bottom_line(clef)


def _written(symbol: Symbol) -> Fraction:
    """Durée écrite (sans point ni nolet), en noires."""
    duration = symbol.duration or Fraction(1)
    duration /= 2 - Fraction(1, 2 ** (symbol.value.get("dots") or 0))
    ratio = symbol.value.get("tuplet")
    if ratio:
        duration = duration * ratio[0] / ratio[1]
    return duration


def _actual(symbol: Symbol, edit: dict) -> Fraction:
    """Durée réelle d'après la durée écrite et les points demandés, nolet gardé."""
    written = edit.get("written")
    if written not in WRITTEN_DURATIONS:
        raise EditError(f"Durée impossible : {written}")
    dots = int(edit.get("dots", symbol.value.get("dots") or 0))
    if not 0 <= dots <= 2:
        raise EditError(f"Nombre de points impossible : {dots}")
    duration = Fraction(written) * (2 - Fraction(1, 2 ** dots))
    ratio = symbol.value.get("tuplet")
    if ratio:
        duration = duration * ratio[1] / ratio[0]
    return duration


def _next_note(model: ScoreModel, note: Symbol) -> Symbol | None:
    """Note suivante de même hauteur dans la même voix (elle-même ou la mesure d'après)."""
    for part in model.parts:
        notes = [s for m in part.measures for s in m.events if s.kind == "note"
                 and not s.value.get("chord")
                 and (s.value.get("voice") or 1) == (note.value.get("voice") or 1)]
        if note in notes:
            index = notes.index(note)
            following = notes[index + 1] if index + 1 < len(notes) else None
            if following is not None and (following.value.get("step"),
                                          following.value.get("octave")) == (
                    note.value.get("step"), note.value.get("octave")):
                return following
            return None
    return None


def _default_pitch(part: Part, measure: Measure, template: Symbol | None) -> tuple[str, int]:
    """Hauteur d'une note ajoutée : celle de la note copiée, sinon le milieu de la portée."""
    if template is not None and template.value.get("step"):
        return template.value["step"], template.value["octave"]
    clef = _state_at(part, measure)["clef"]
    return from_degree(_bottom_line(clef) + 4)
