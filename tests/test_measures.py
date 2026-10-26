"""Tests du découpage en mesures (réunir deux mesures, couper une mesure) et de l'édition à
la main des signes d'expression : calcul, journal, annulation, questions, reprise."""

import pytest

from recomuse import editing
from recomuse.learning import memory
from recomuse.learning.corrections import CorrectionService
from recomuse.model.measures import MeasureEditError, merge_with_next, split_after
from recomuse.model.store import load_model, save_model
from recomuse.questions.session import QuestionSession

from validation_helpers import attribute, four_four, measure, model_of, note, treble


def quarters(ident: str, count: int, octave: int = 5):
    return [note(f"{ident}.n{k}", "C", octave, "1", x=100 + 50 * k) for k in range(count)]


def false_bar():
    """Mesure 2 coupée en deux par une barre en trop (2 + 2 temps)."""
    return model_of([
        measure("m1", quarters("m1", 4), [treble(), four_four()], bbox=(0.0, 0.0, 400.0, 100.0)),
        measure("m2", quarters("m2", 2), bbox=(400.0, 0.0, 200.0, 100.0)),
        measure("m3", quarters("m3", 2), bbox=(600.0, 0.0, 200.0, 100.0)),
        measure("m4", quarters("m4", 4), bbox=(800.0, 0.0, 400.0, 100.0))])


def missed_bar():
    """Mesure 2 qui en contient deux (8 temps) : une barre manquée."""
    return model_of([
        measure("m1", quarters("m1", 4), [treble(), four_four()]),
        measure("m2", quarters("m2", 8), bbox=(400.0, 0.0, 800.0, 100.0)),
        measure("m3", quarters("m3", 4))])


@pytest.fixture
def service(conn, tmp_path):
    return CorrectionService(conn, tmp_path / "extraits")


@pytest.fixture
def session(conn, service, tmp_path):
    return QuestionSession(conn, service, work_dir=tmp_path / "travail")


# --- Calcul --------------------------------------------------------------------------------


def test_merge_joins_events_and_boxes():
    change = merge_with_next(false_bar(), "m2")
    [merged] = change.new
    assert [e.id for e in merged.events] == ["m2.n0", "m2.n1", "m3.n0", "m3.n1"]
    assert merged.bbox == (400.0, 0.0, 400.0, 100.0)
    assert (change.index, [m.id for m in change.old]) == (1, ["m2", "m3"])


def test_merge_refuses_a_real_change_or_a_long_rest():
    model = false_bar()
    model.parts[0].measures[2].attributes.append(attribute("t2", "time", beats=2, beat_type=4))
    model.parts[0].measures[1].attributes.append(attribute("t1", "time", beats=2, beat_type=4))
    with pytest.raises(MeasureEditError) as info:
        merge_with_next(model, "m2")
    assert info.value.code == "merge_conflict"
    with pytest.raises(MeasureEditError) as info:
        merge_with_next(model, "m4")
    assert info.value.code == "no_next_measure"


def test_split_cuts_after_the_note_and_keeps_chords_together():
    model = missed_bar()
    events = model.parts[0].measures[1].events
    events.insert(4, note("m2.c", "E", 5, "1", chord=True))      # accord sur la 4e note
    change = split_after(model, "m2.n3")
    first, second = change.new
    assert [e.id for e in first.events][-2:] == ["m2.n3", "m2.c"]
    assert [e.id for e in second.events] == ["m2.n4", "m2.n5", "m2.n6", "m2.n7"]
    assert second.id == "m2+0" and change.selected == "m2+0"
    with pytest.raises(MeasureEditError) as info:
        split_after(model, "m2.n7")
    assert info.value.code == "split_at_end"


# --- Journal et annulation -------------------------------------------------------------------


def test_restructure_is_journaled_and_undone(conn, service, score_id):
    save_model(conn, score_id, false_bar())
    before = load_model(conn, score_id).to_dict()
    correction = service.restructure(score_id, merge_with_next(load_model(conn, score_id), "m2"),
                                     source="manual")
    model = load_model(conn, score_id)
    assert [m.number for m in model.parts[0].measures] == [1, 2, 3]
    service.revert(correction)
    assert load_model(conn, score_id).to_dict() == before


def test_manual_merge_split_and_undo(conn, service, score_id):
    save_model(conn, score_id, missed_bar())
    result = editing.apply_edit(conn, service, score_id, {"op": "split_after",
                                                          "symbol_id": "m2.n3"})
    assert result["measure_id"] == "m2+0"
    assert [m.id for m in load_model(conn, score_id).parts[0].measures] == ["m1", "m2", "m2+0",
                                                                           "m3"]
    assert editing.undo_last_edit(conn, service, score_id) == "m2"
    assert [m.id for m in load_model(conn, score_id).parts[0].measures] == ["m1", "m2", "m3"]
    with pytest.raises(editing.EditError) as info:
        editing.apply_edit(conn, service, score_id, {"op": "merge_next", "measure_id": "m3"})
    assert info.value.code == "no_next_measure"


# --- Questions ------------------------------------------------------------------------------


def test_a_false_bar_is_asked_and_the_answer_merges(conn, session, score_id):
    save_model(conn, score_id, false_bar())
    questions = session.state(score_id)["questions"]
    question = next(q for q in questions if q["code"] == "measures_merge_suspicious")
    assert question["measure_numbers"] == [2, 3]
    state = session.answer(score_id, question["key"], "accept")
    assert [m.id for m in load_model(conn, score_id).parts[0].measures] == ["m1", "m2", "m4"]
    assert state["questions"] == [] and state["unasked"] == 0
    # Annuler la réponse remet la barre.
    session.undo(score_id)
    assert len(load_model(conn, score_id).parts[0].measures) == 4


def test_a_missed_bar_is_asked_and_the_answer_splits(conn, session, score_id):
    save_model(conn, score_id, missed_bar())
    [question] = session.state(score_id)["questions"]
    assert question["code"] == "measure_split_suspicious"
    state = session.answer(score_id, question["key"], "accept")
    model = load_model(conn, score_id)
    assert [len(m.events) for m in model.parts[0].measures] == [4, 4, 4, 4]
    assert state["questions"] == []


def test_a_merge_is_replayed_on_the_same_reading(conn, service, score_id):
    save_model(conn, score_id, false_bar())
    service.restructure(score_id, merge_with_next(load_model(conn, score_id), "m2"),
                        source="manual")
    with conn:
        cursor = conn.execute("INSERT INTO scores (title, source_path) VALUES ('x', 'y.pdf')")
    new = cursor.lastrowid
    save_model(conn, new, false_bar())
    result = memory.replay(conn, service, score_id, new)
    assert (result["applied"], result["skipped"]) == (1, 0)
    assert [m.id for m in load_model(conn, new).parts[0].measures] == ["m1", "m2", "m4"]


# --- Signes d'expression à la main --------------------------------------------------------------


def test_editing_marks(conn, service, score_id):
    save_model(conn, score_id, false_bar())

    def edit(**gesture):
        editing.apply_edit(conn, service, score_id, gesture)
        return load_model(conn, score_id).find("m1.n0")[2].value

    assert edit(op="articulation", symbol_id="m1.n0", name="accent")["articulations"] == [
        "accent"]
    assert edit(op="articulation", symbol_id="m1.n0", name="accent")["articulations"] == []
    assert edit(op="dynamic", symbol_id="m1.n0", value="ff")["dynamic"] == "ff"
    assert edit(op="dynamic", symbol_id="m1.n0", value="")["dynamic"] is None
    assert edit(op="slur", symbol_id="m1.n0", end="start")["slur_start"] is True
    assert edit(op="wedge", symbol_id="m1.n0", value="diminuendo")["wedge_start"] == "diminuendo"
    assert edit(op="wedge", symbol_id="m1.n0", value="none")["wedge_start"] is None
    with pytest.raises(editing.EditError):
        edit(op="dynamic", symbol_id="m1.n0", value="fortissimo")

    editing.apply_edit(conn, service, score_id, {"op": "tempo", "measure_id": "m3",
                                                 "text": "Andante", "per_minute": "76"})
    [tempo] = [s for s in load_model(conn, score_id).find_measure("m3")[1].attributes
               if s.kind == "tempo"]
    assert tempo.value == {"text": "Andante", "beat": "1", "per_minute": 76}
    editing.apply_edit(conn, service, score_id, {"op": "tempo", "measure_id": "m3",
                                                 "text": "", "per_minute": ""})
    assert not load_model(conn, score_id).find_measure("m3")[1].attributes
