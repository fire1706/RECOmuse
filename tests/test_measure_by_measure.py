"""Tests de la vérification mesure par mesure :
- les questions viennent dans l'ordre de la partition ;
- un chiffrage manqué sur un passage (2/4 au milieu du 4/4) se corrige d'une réponse, qui
  remet aussi l'ancien chiffrage après le passage (pas d'erreurs en cascade) ;
- une clé mal lue (sol au lieu de fa) est demandée, et la réponse renomme ses notes.
"""

import pytest

from recomuse.instruments.table import Instrument, InstrumentTable, parse_note
from recomuse.learning.corrections import CorrectionService
from recomuse.model.store import load_model, save_model
from recomuse.questions.questions import build_questions
from recomuse.questions.session import QuestionSession
from recomuse.validation import validate
from recomuse.validation.issues import Fix, Issue, ValidationReport

from validation_helpers import attribute, four_four, measure, model_of, note, treble


def quarters(ident: str, count: int, step: str = "C", octave: int = 5):
    return [note(f"{ident}.n{k}", step, octave, "1") for k in range(count)]


def bass(ident: str = "c") -> object:
    return attribute(ident, "clef", sign="F", line=4)


@pytest.fixture
def session(conn, tmp_path):
    return QuestionSession(conn, CorrectionService(conn, tmp_path / "extraits"),
                           work_dir=tmp_path / "travail")


# --- Ordre ------------------------------------------------------------------------------


def test_questions_follow_the_score_measure_by_measure():
    model = model_of([measure(f"m{k}", quarters(f"m{k}", 4), [treble(), four_four()] if k == 1
                              else []) for k in range(1, 6)])
    # Une note douteuse en mesure 2, un silence à vérifier en mesure 4, une note en 5 :
    # avant, les silences passaient en premier ; maintenant, la partition se lit dans l'ordre.
    late_note = Issue("note_position_mismatch", "P1", [5], "warning", 0.7)
    late_note.fixes.append(Fix("m5.n0", {"octave": 4}))
    rest = Issue("multirest_missed", "P1", [4], "error", 0.6,
                 details={"count": 8}, action={"set_multirest": 8, "measure_id": "m4"})
    early_note = Issue("note_position_mismatch", "P1", [2], "warning", 0.7)
    early_note.fixes.append(Fix("m2.n0", {"octave": 4}))
    questions, _ = build_questions(model, ValidationReport([late_note, rest, early_note]))
    assert [q.measure_numbers[0] for q in questions] == [2, 4, 5]


def test_in_one_measure_the_questions_that_fix_more_come_first():
    model = model_of([measure("m1", quarters("m1", 4), [treble(), four_four()]),
                      measure("m2", quarters("m2", 4))])
    note_issue = Issue("note_position_mismatch", "P1", [2], "warning", 0.7,
                       fixes=[Fix("m2.n0", {"octave": 4})])
    rest = Issue("multirest_missed", "P1", [2], "error", 0.6,
                 details={"count": 8}, action={"set_multirest": 8, "measure_id": "m2"})
    questions, _ = build_questions(model, ValidationReport([note_issue, rest]))
    assert [q.code for q in questions] == ["multirest_missed", "note_position_mismatch"]


# --- Chiffrage : passage délimité --------------------------------------------------------


def two_four_section():
    """4/4, puis deux mesures de 2 temps (chiffrage 2/4 manqué), puis de nouveau 4/4."""
    measures = [measure("m1", quarters("m1", 4), [treble(), four_four()]),
                measure("m2", quarters("m2", 4)),
                measure("m3", quarters("m3", 2)),
                measure("m4", quarters("m4", 2)),
                measure("m5", quarters("m5", 4)),
                measure("m6", quarters("m6", 4))]
    return model_of(measures)


def test_a_bounded_section_proposes_the_change_and_the_return():
    model = two_four_section()
    [question], unasked = build_questions(model, validate(model))
    assert unasked == []
    assert question.code == "time_signature_missed"
    assert question.params == {"time": "2/4", "measures": 2, "back": "4/4",
                               "first": 3, "last": 4}
    accept = question.choices[0]
    assert (accept.label, accept.params) == ("time_section", {"time": "2/4", "back": "4/4"})
    _, additions = accept.changes()
    assert [(a.measure_id, a.kind, a.value) for a in additions] == [
        ("m3", "time", {"beats": 2, "beat_type": 4}),
        ("m5", "time", {"beats": 4, "beat_type": 4})]


def test_answering_the_section_leaves_no_cascade(conn, session, score_id):
    save_model(conn, score_id, two_four_section())
    [question] = session.state(score_id)["questions"]
    state = session.answer(score_id, question["key"], "accept")
    # Une seule réponse : plus aucune question ni mesure à vérifier, et les mesures 5 et
    # 6 sont de nouveau attendues à 4 temps.
    assert state["questions"] == [] and state["unasked"] == 0
    model = load_model(conn, score_id)
    assert [m.expected_duration for m in model.parts[0].measures] == ["4", "4", "2", "2",
                                                                      "4", "4"]


def test_an_open_ended_change_still_needs_three_measures():
    # Deux mesures de 2 temps en fin de partie : pas de retour visible, pas assez pour
    # conclure (ce peut être deux mesures mal lues).
    model = model_of([measure("m1", quarters("m1", 4), [treble(), four_four()]),
                      measure("m2", quarters("m2", 4)),
                      measure("m3", quarters("m3", 2)),
                      measure("m4", quarters("m4", 2))])
    questions, unasked = build_questions(model, validate(model))
    assert questions == [] and len(unasked) == 2


# --- Clés ---------------------------------------------------------------------------------


def tuba_with_treble_from_measure_3():
    """Partie de tuba en clé de fa ; Audiveris a lu une clé de sol au 3e système. Les notes
    (mi♭2, ré2, do2, si♭1 sur la portée) ont donc été nommées comme en clé de sol."""
    key = attribute("k", "key", fifths=-3)
    measures = [measure("m1", quarters("m1", 4, "E", 2), [bass(), key, four_four()]),
                measure("m2", quarters("m2", 4, "D", 2)),
                # Mêmes places sur la portée, lues en clé de sol : douze degrés plus haut.
                measure("m3", quarters("m3", 4, "C", 4), [treble("c2")]),
                measure("m4", quarters("m4", 4, "B", 3))]
    return model_of(measures, name="Tuba")


def test_a_clef_that_changes_in_the_part_is_asked():
    model = tuba_with_treble_from_measure_3()
    questions, _ = build_questions(model, validate(model))
    [question] = [q for q in questions if q.code == "clef_sign_suspicious"]
    assert question.measure_numbers == [3]
    assert question.params == {"read": "treble", "proposed": "bass", "notes": 8,
                               "reason": "change"}
    accept, keep = question.choices
    assert (accept.label, keep.label) == ("clef_bass", "clef_treble")
    fixes, _ = accept.changes()
    assert fixes[0].symbol_id == "c2" and fixes[0].value == {"sign": "F", "line": 4,
                                                            "octave_change": 0}
    # Les notes gardent leur place : do4 → mi2, avec le bémol de l'armure (3 bémols).
    renamed = {f.symbol_id: f.value for f in fixes[1:]}
    assert renamed["m3.n0"] == {"step": "E", "octave": 2, "alter": -1}
    assert renamed["m4.n0"] == {"step": "D", "octave": 2, "alter": 0}
    assert keep.changes() == ([], [])


def test_answering_the_clef_renames_the_notes(conn, session, score_id):
    save_model(conn, score_id, tuba_with_treble_from_measure_3())
    question = next(q for q in session.state(score_id)["questions"]
                    if q["code"] == "clef_sign_suspicious")
    session.answer(score_id, question["key"], "accept")
    part = load_model(conn, score_id).parts[0]
    clef = next(s for s in part.measures[2].attributes if s.kind == "clef")
    assert (clef.value["sign"], clef.value["line"]) == ("F", 4)
    assert [(n.value["step"], n.value["octave"]) for n in part.measures[2].events][:1] == [
        ("E", 2)]


def test_a_clef_the_instrument_cannot_use_is_asked():
    # Trompette (clé de sol seulement) lue en clé de fa : ses notes sortent toutes de
    # l'étendue ; en clé de sol, elles y rentrent.
    measures = [measure("m1", quarters("m1", 4, "B", 2), [bass(), four_four()]),
                measure("m2", quarters("m2", 4, "A", 2))]
    model = model_of(measures, name="Trumpet in Bb")
    questions, _ = build_questions(model, validate(model))
    [question] = questions
    assert question.code == "clef_sign_suspicious"
    assert question.params["reason"] == "range"
    assert (question.params["read"], question.params["proposed"]) == ("bass", "treble")
    # Les notes hors tessiture ne font pas l'objet d'une seconde question.
    assert all(q.code != "note_out_of_range" for q in questions)


def test_a_clef_change_both_clefs_explain_is_asked():
    # Trombone qui passe en clé d'ut 4e ligne : les deux clés vont à l'instrument, rien ne
    # tranche ; on demande (un clic si le changement est réel).
    tenor = attribute("c2", "clef", sign="C", line=4)
    measures = [measure("m1", quarters("m1", 4, "C", 3), [bass(), four_four()]),
                measure("m2", quarters("m2", 4, "G", 4), [tenor])]
    model = model_of(measures, name="Trombone")
    questions, _ = build_questions(model, validate(model))
    [question] = [q for q in questions if q.code == "clef_sign_suspicious"]
    assert (question.params["read"], question.params["proposed"]) == ("tenor", "bass")


def test_a_clef_change_only_the_new_clef_explains_is_not_asked():
    # Instrument dont l'étendue tranche : avec l'ancienne clé (sol), les notes du passage
    # sortiraient de l'étendue ; avec la nouvelle (fa), elles y sont. Vrai changement.
    table = InstrumentTable([Instrument(id="test", names=("essai",),
                                        ranges={"G": (parse_note("E4"), parse_note("C6")),
                                                "F": (parse_note("C2"), parse_note("C3"))})])
    measures = [measure("m1", quarters("m1", 4, "G", 4), [treble(), four_four()]),
                measure("m2", quarters("m2", 4, "E", 2), [bass("c2")])]
    model = model_of(measures, name="Essai")
    assert all(i.code != "clef_sign_suspicious" for i in validate(model, table=table).issues)


def test_a_part_without_a_clef_at_the_start_gets_the_clef_read_later():
    # Partie de tuba : Audiveris n'a placé la clé de fa qu'à la 3e mesure, mais avait bien
    # nommé les notes d'avant (la♭2, sol2...) : on ajoute la clé, sans renommer.
    measures = [measure("m1", quarters("m1", 4, "A", 2), [four_four()]),
                measure("m2", quarters("m2", 4, "G", 2)),
                measure("m3", quarters("m3", 4, "F", 2), [bass("c2")])]
    model = model_of(measures, name="Tuba")
    [question] = [q for q in build_questions(model, validate(model))[0]
                  if q.code == "clef_sign_suspicious"]
    assert question.measure_numbers == [1]
    assert question.params["reason"] == "missing" and question.params["proposed"] == "bass"
    fixes, additions = question.choices[0].changes()
    assert fixes == []
    assert [(a.measure_id, a.kind, a.value) for a in additions] == [
        ("m1", "clef", {"sign": "F", "line": 4, "octave_change": 0})]


def test_notes_named_as_treble_without_a_clef_are_renamed():
    # Partie sans aucune clé, notes nommées comme en clé de sol, pour un instrument qui ne
    # joue qu'en clé de fa : ses notes ne rentrent dans l'étendue qu'une fois renommées.
    table = InstrumentTable([Instrument(id="test", names=("essai",),
                                        ranges={"F": (parse_note("C2"), parse_note("C3"))})])
    measures = [measure("m1", quarters("m1", 4, "C", 4), [four_four()]),
                measure("m2", quarters("m2", 4, "D", 4))]
    model = model_of(measures, name="Essai")
    [issue] = [i for i in validate(model, table=table).issues
               if i.code == "clef_sign_suspicious"]
    assert issue.details["reason"] == "missing" and issue.details["rename"] is True
    # do4 en clé de sol (3e interligne... ligne du bas + 12 degrés) → mi2 en clé de fa.
    assert issue.fixes[0].value == {"step": "E", "octave": 2, "alter": 0}
