"""Tests du passage des doutes du validateur aux questions (questions/questions.py)."""

import pytest

from recomuse.learning.corrections import NewSymbol
from recomuse.questions.questions import build_questions
from recomuse.validation import validate
from recomuse.validation.issues import Fix, Issue, ValidationReport

from validation_helpers import attribute, four_four, measure, model_of, note, rest, treble


def quarters(ident: str, count: int, octave: int = 5):
    return [note(f"{ident}.n{k}", "C", octave, "1") for k in range(count)]


def three_four_model():
    """Une mesure en 4/4, puis quatre mesures de 3 temps : le chiffrage 3/4 a été manqué."""
    measures = [measure("m1", quarters("m1", 4), [treble(), four_four()])]
    measures += [measure(f"m{k}", quarters(f"m{k}", 3)) for k in range(2, 6)]
    return model_of(measures)


def test_missed_time_signature_becomes_one_question():
    model = three_four_model()
    questions, unasked = build_questions(model, validate(model))
    assert unasked == 0
    [question] = questions
    assert question.code == "time_signature_missed"
    assert question.key == "time_signature_missed:P1:m2,m3,m4,m5"
    assert question.params == {"time": "3/4", "measures": 4}
    accept, keep = question.choices
    assert (accept.label, accept.params) == ("time_is", {"time": "3/4"})
    assert accept.changes() == ([], [NewSymbol("m2", "time", {"beats": 3, "beat_type": 4})])
    assert (keep.label, keep.params) == ("time_unchanged", {"time": "4/4"})
    assert keep.changes() == ([], [])


def test_wrong_measure_without_proposal_is_not_a_question():
    model = model_of([measure("m1", quarters("m1", 4), [treble(), four_four()]),
                      measure("m2", quarters("m2", 3)),
                      measure("m3", quarters("m3", 4))])
    questions, unasked = build_questions(model, validate(model))
    assert questions == [] and unasked == 1


def multirest_model():
    return model_of([measure("m1", quarters("m1", 4), [treble(), four_four()]),
                     measure("m2", [rest("m2.r", "4", full=True)]),
                     measure("m3", [], [attribute("mr", "multirest", count=1)]),
                     measure("m4", quarters("m4", 4))])


def test_multirest_questions_and_their_choices():
    model = multirest_model()
    missed = Issue("multirest_missed", "P1", [2], "error", 0.6, symbol_ids=["m2.r"],
                   details={"count": 8}, action={"set_multirest": 8, "measure_id": "m2"})
    # Même pause, autre indice : les numéros imprimés sautent de 7 mesures.
    numbering = Issue("measure_number_mismatch", "P1", [2], "error", 0.85,
                      details={"printed_before": 1, "printed_after": 10, "missing": 7},
                      action={"set_multirest": 8, "measure_id": "m2"})
    unknown = Issue("multirest_count_unknown", "P1", [3], "warning", 0.8, symbol_ids=["mr"])
    questions, _ = build_questions(model, ValidationReport([unknown, numbering, missed]))

    first, second = questions
    assert first.key == "multirest:P1:m2" and first.issue_count == 2
    assert first.code == "multirest_missed"                      # posée dans cet ordre
    assert [c.id for c in first.choices] == ["accept", "count", "keep"]
    accept, other, keep = first.choices
    assert accept.params == {"count": 8}
    assert accept.changes() == ([], [NewSymbol("m2", "multirest", {"count": 8})])
    assert other.changes(12) == ([], [NewSymbol("m2", "multirest", {"count": 12})])
    assert other.changes(1) == ([], [])
    with pytest.raises(ValueError):
        other.changes(0)
    assert keep.changes() == ([], [])

    # Pause multiple déjà là, nombre inconnu : on demande le nombre, il n'y a rien d'autre.
    assert second.key == "multirest:P1:m3"
    assert [c.id for c in second.choices] == ["count"]
    fixes, additions = second.choices[0].changes(5)
    assert [(f.symbol_id, f.value) for f in fixes] == [("mr", {"count": 5})] and not additions


def test_numbering_jump_without_a_rest_is_not_a_question():
    model = multirest_model()
    jump = Issue("measure_number_mismatch", "P1", [4], "error", 0.7,
                 details={"printed_before": 1, "printed_after": 10, "missing": 2})
    questions, unasked = build_questions(model, ValidationReport([jump]))
    assert questions == [] and unasked == 1


def test_notes_out_of_range_are_grouped_by_direction():
    model = model_of([measure("m1", quarters("m1", 4, octave=7), [treble(), four_four()]),
                      measure("m2", quarters("m2", 2, octave=7) + quarters("m2b", 2, octave=2))])
    high = [Issue("note_out_of_range", "P1", [n], "warning", 0.6, symbol_ids=[s],
                  details={"instrument": "flute", "note": "C7", "direction": "high"},
                  fixes=[Fix(s, {"octave": 6})])
            for n, s in [(1, "m1.n0"), (1, "m1.n1"), (2, "m2.n0")]]
    low = [Issue("note_out_of_range", "P1", [2], "warning", 0.6, symbol_ids=["m2b.n0"],
                 details={"instrument": "flute", "note": "C2", "direction": "low"},
                 fixes=[Fix("m2b.n0", {"octave": 3})])]
    questions, _ = build_questions(model, ValidationReport(high + low))
    by_direction = {q.params["direction"]: q for q in questions}
    up = by_direction["high"]
    assert up.issue_count == 3 and up.params["count"] == 3
    assert up.measure_numbers == [1, 2]
    assert up.params["notes"][0] == {"step": "C", "octave": 7, "alter": 0}
    assert [c.label for c in up.choices] == ["octave_down", "notes_correct"]
    assert len(up.choices[0].changes()[0]) == 3
    assert by_direction["low"].choices[0].label == "octave_up"


def test_note_and_clef_questions():
    model = model_of([measure("m1", [note("n1", "C", 5, "4", position=10, x=300)],
                              [treble("c", confidence=0.4), four_four()])])
    position = Issue("note_position_mismatch", "P1", [1], "error", 0.7, symbol_ids=["n1"],
                     fixes=[Fix("n1", {"step": "C", "octave": 6})])
    clef = Issue("clef_octave_suspicious", "P1", [1], "error", 0.6, symbol_ids=["n1"],
                 details={"octave_change": -1, "notes": 1},
                 fixes=[Fix("c", {"octave_change": 0}), Fix("n1", {"octave": 6})])
    questions, _ = build_questions(model, ValidationReport([position, clef]))
    assert [q.code for q in questions] == ["clef_octave_suspicious", "note_position_mismatch"]
    clef_question, note_question = questions
    assert [c.label for c in clef_question.choices] == ["clef_plain", "clef_octave"]
    assert len(clef_question.choices[0].changes()[0]) == 2
    assert [c.params["note"]["octave"] for c in note_question.choices] == [6, 5]
    # La tête de note est entourée, et la zone montrée la contient (avec une marge).
    assert note_question.highlights == [(300, 170.0, 24, 20)]
    x, y, w, h = note_question.region
    assert x <= 300 and y <= 170 and x + w >= 324 and y + h >= 190
    assert note_question.page == 1


def test_to_dict_is_plain_data():
    model = three_four_model()
    [question] = build_questions(model, validate(model))[0]
    data = question.to_dict()
    assert data["choices"][0] == {"id": "accept", "label": "time_is",
                                  "params": {"time": "3/4"}, "input": None}
    assert "fixes" not in data["choices"][0]
