"""Contrôle de la tessiture : une note hors de l'étendue de l'instrument est suspecte.

C'est presque toujours une erreur d'octave : si la note, déplacée d'une octave, rentre
dans l'étendue, on le propose. L'instrument est reconnu d'après le nom de la partie
(table des instruments).
"""

from recomuse.instruments.table import InstrumentTable, load_table, midi_number
from recomuse.model.score import ScoreModel
from recomuse.validation.issues import Fix, Issue
from recomuse.validation.pitches import notes_with_clef


def check_ranges(model: ScoreModel, table: InstrumentTable | None = None) -> list[Issue]:
    table = table or load_table()
    issues = []
    for part in model.parts:
        name = part.name or (model.instrument if len(model.parts) == 1 else None)
        instrument = table.find(name)
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
