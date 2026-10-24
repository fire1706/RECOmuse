"""Tests de l'édition manuelle (editing.py) : gestes → corrections « manual »."""

import pytest

from recomuse import editing
from recomuse.api import Api
from recomuse.learning.corrections import CorrectionService
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.store import load_model, save_model

from validation_helpers import attribute, four_four, measure, model_of, note, rest, treble


@pytest.fixture
def stored(conn, score_id):
    """Fa majeur 4/4 : si♭4 (armure), do5, la4, sol4 ; puis une mesure de silence ; puis
    si♭4 et une blanche fa4."""
    model = model_of([
        measure("m1", [note("a", "B", 4, "1", alter=-1), note("b", "C", 5, "1"),
                       note("la", "A", 4, "1"), note("d", "G", 4, "1")],
                [treble(), attribute("k", "key", fifths=-1), four_four()]),
        measure("m2", [rest("r", "4", full=True)]),
        measure("m3", [note("e", "B", 4, "1", alter=-1), note("f", "F", 4, "2")]),
    ])
    save_model(conn, score_id, model)
    return model


@pytest.fixture
def service(conn, tmp_path):
    return CorrectionService(conn, tmp_path / "extraits")


def edit(conn, service, score_id, **gesture):
    return editing.apply_edit(conn, service, score_id, gesture)


def value(conn, score_id, symbol_id):
    return load_model(conn, score_id).find(symbol_id)[2].value


def test_measure_details(stored):
    details = editing.measure_details(stored, "m3")
    assert details["number"] == 3 and details["previous"] == "m2" and details["next"] is None
    assert details["state"] == {"clef": {"sign": "G", "line": 2}, "fifths": -1, "time": "4/4"}
    assert (details["duration"], details["expected"]) == ("3", "4")
    assert [e["value"]["written"] for e in details["events"]] == ["1", "2"]


def test_pitch_steps_follow_the_key(conn, service, score_id, stored):
    edit(conn, service, score_id, op="pitch", symbol_id="b", steps=-1)   # do5 → si4 (♭)
    assert (value(conn, score_id, "b")["step"], value(conn, score_id, "b")["alter"]) == ("B", -1)
    edit(conn, service, score_id, op="pitch", symbol_id="b", steps=2)    # si4 → ré5
    assert (value(conn, score_id, "b")["step"], value(conn, score_id, "b")["octave"]) == ("D", 5)
    edit(conn, service, score_id, op="octave", symbol_id="b", change=-1)
    edit(conn, service, score_id, op="alter", symbol_id="b", alter=1)
    assert (value(conn, score_id, "b")["octave"], value(conn, score_id, "b")["alter"]) == (4, 1)
    entry = CorrectionJournal(conn).list_for_score(score_id)[-1]
    assert entry.source == "manual" and entry.reason == "edit:alter"


def test_duration_keeps_the_dots_and_the_tuplet(conn, service, score_id, stored):
    edit(conn, service, score_id, op="duration", symbol_id="f", written="1/2", dots=1)
    f = value(conn, score_id, "f")
    assert (f["duration"], f["dots"]) == ("3/4", 1)
    edit(conn, service, score_id, op="duration", symbol_id="r", written="2", dots=0)
    assert value(conn, score_id, "r") == {"duration": "2", "dots": 0, "voice": 1,
                                          "full_measure": False}
    with pytest.raises(editing.EditError):
        edit(conn, service, score_id, op="duration", symbol_id="f", written="3")


def test_tie_links_the_next_note_of_same_pitch(conn, service, score_id, stored):
    edit(conn, service, score_id, op="tie", symbol_id="a")              # si♭4 → do5 : seule
    assert value(conn, score_id, "a")["tie_start"] is True
    assert "tie_stop" not in value(conn, score_id, "b")
    edit(conn, service, score_id, op="tie", symbol_id="a")              # déliée
    edit(conn, service, score_id, op="pitch", symbol_id="b", steps=-1)  # do5 → si♭4
    edit(conn, service, score_id, op="tie", symbol_id="a")
    assert value(conn, score_id, "a")["tie_start"] is True
    assert value(conn, score_id, "b")["tie_stop"] is True


def test_add_and_remove_notes_then_undo(conn, service, score_id, stored):
    result = edit(conn, service, score_id, op="add_note", measure_id="m3", after="f")
    added = result["symbol_id"]
    assert added == "m3.note+0" and result["measure_id"] == "m3"
    new = value(conn, score_id, added)
    assert (new["step"], new["octave"], new["duration"]) == ("F", 4, "2")   # copie de f
    edit(conn, service, score_id, op="remove", symbol_id="e")
    assert [s.id for s in load_model(conn, score_id).find_measure("m3")[1].events] == \
        ["f", added]

    assert editing.undo_last_edit(conn, service, score_id) == "m3"       # la suppression
    assert editing.undo_last_edit(conn, service, score_id) == "m3"       # l'ajout
    assert [s.id for s in load_model(conn, score_id).find_measure("m3")[1].events] == ["e", "f"]
    assert editing.undo_last_edit(conn, service, score_id) is None

    rest_added = edit(conn, service, score_id, op="add_rest", measure_id="m2", written="1/2")
    assert value(conn, score_id, rest_added["symbol_id"])["duration"] == "1/2"
    first = edit(conn, service, score_id, op="add_note", measure_id="m2")   # milieu de portée
    assert (value(conn, score_id, first["symbol_id"])["step"],
            value(conn, score_id, first["symbol_id"])["octave"]) == ("B", 4)


def test_time_key_clef_and_multirest(conn, service, score_id, stored):
    edit(conn, service, score_id, op="time", measure_id="m3", beats=3, beat_type=4)
    model = load_model(conn, score_id)
    assert model.find_measure("m3")[1].expected_duration == "3"
    edit(conn, service, score_id, op="time", measure_id="m1", beats=2, beat_type=4)
    assert load_model(conn, score_id).find("t")[2].value == {"beats": 2, "beat_type": 4}

    # Fa majeur → do majeur : les si bémols de l'armure deviennent si naturels.
    edit(conn, service, score_id, op="key", measure_id="m1", fifths=0)
    assert value(conn, score_id, "a")["alter"] == 0 and value(conn, score_id, "e")["alter"] == 0
    # Clé de sol → clé de fa : les notes restent à leur place sur la portée.
    edit(conn, service, score_id, op="clef", measure_id="m1", sign="F", line=4)
    a = value(conn, score_id, "a")
    assert (a["step"], a["octave"]) == ("D", 3)          # si4 en sol = ré3 en fa
    # Les trois modifications de l'armure partent ensemble à l'annulation.
    editing.undo_last_edit(conn, service, score_id)
    editing.undo_last_edit(conn, service, score_id)
    assert value(conn, score_id, "a") == {**value(conn, score_id, "a"), "step": "B",
                                          "octave": 4, "alter": -1}

    edit(conn, service, score_id, op="multirest", measure_id="m2", count=8)
    assert load_model(conn, score_id).find_measure("m3")[1].number == 10
    edit(conn, service, score_id, op="multirest", measure_id="m2", count=1)
    assert load_model(conn, score_id).find_measure("m3")[1].number == 3
    for wrong in [{"op": "time", "measure_id": "m1", "beats": 3, "beat_type": 5},
                  {"op": "key", "measure_id": "m1", "fifths": 9},
                  {"op": "clef", "measure_id": "m1", "sign": "X"},
                  {"op": "multirest", "measure_id": "m2", "count": 0},
                  {"op": "pitch", "symbol_id": "r", "steps": 1},
                  {"op": "inconnu"}, {"op": "remove", "symbol_id": "absent"}]:
        with pytest.raises(editing.EditError):
            edit(conn, service, score_id, **wrong)


def test_api_edit_methods(conn, score_id, stored):
    api = Api(conn, ":memory:")
    details = api.get_measure(score_id, "m1")
    assert details["number"] == 1 and details["can_undo"] is False
    result = api.edit_score(score_id, {"op": "octave", "symbol_id": "b", "change": 1})
    assert result["symbol_id"] == "b" and len(result["corrections"]) == 1
    assert api.get_measure(score_id, "m1")["can_undo"] is True
    assert api.undo_edit(score_id) == {"measure_id": "m1"}
    assert api.undo_edit(score_id) == {"error": "edit_failed"}
    assert api.edit_score(score_id, {"op": "inconnu"}) == {"error": "edit_failed"}
    assert api.get_measure(score_id, "absente") == {"error": "edit_failed"}
