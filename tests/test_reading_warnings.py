"""Tests des avertissements de lecture (gardés avec la partition, montrés à l'utilisateur)
et des mesures vides (une question : silence, pause de plusieurs mesures, ou notes)."""

import pytest

from recomuse import library
from recomuse.learning.corrections import CorrectionService
from recomuse.model.score import PageInfo, ScoreModel
from recomuse.model.store import load_model, save_model
from recomuse.questions.questions import build_questions
from recomuse.questions.session import QuestionSession
from recomuse.validation import validate

from validation_helpers import attribute, four_four, measure, model_of, note, treble


def quarters(ident: str, count: int):
    return [note(f"{ident}.n{k}", "C", 5, "1") for k in range(count)]


# --- Avertissements de lecture -----------------------------------------------------------


def test_warnings_are_grouped_by_kind_with_the_lowest_resolution():
    model = ScoreModel(pages=[
        PageInfo(1, None, source_dpi=150.0, warnings=["low_resolution", "dpi_estimated"]),
        PageInfo(2, None, source_dpi=68.4, warnings=["low_resolution", "large_skew"]),
        PageInfo(3, None, warnings=["audiveris_skipped"]),
        PageInfo(4, None, source_dpi=300.0)])
    assert library.reading_warnings(model) == [
        {"code": "low_resolution", "pages": [1, 2], "dpi": 68},
        {"code": "audiveris_skipped", "pages": [3]},
        {"code": "large_skew", "pages": [2]}]
    # Le résumé d'une partition les porte, pour l'interface.
    assert library.summary(1, model)["warnings"] == library.reading_warnings(model)


def test_a_model_saved_before_the_warnings_still_loads(conn, score_id):
    model = model_of([measure("m1", quarters("m1", 4), [treble(), four_four()])])
    data = model.to_dict()
    for page in data["pages"]:
        del page["source_dpi"], page["warnings"]
    loaded = ScoreModel.from_dict(data)
    assert loaded.pages[0].warnings == [] and loaded.pages[0].source_dpi is None


def test_a_page_audiveris_crashed_on_is_reported(monkeypatch, tmp_path):
    from recomuse.importer import ImportedPage, ImportedScore
    from recomuse.model.build import build_model
    from recomuse.recognition import RecognitionResult
    from recomuse.recognition.header import HeaderInfo

    pages = [ImportedPage(page_number=n, kind="scanned", image_path=tmp_path / f"p{n}.png",
                          source_dpi=72.0, warnings=["low_resolution"]) for n in (1, 2)]
    score = ImportedScore(source_path=tmp_path / "s.pdf", source_kind="scanned_pdf",
                          work_dir=tmp_path, pages=pages)
    recognition = RecognitionResult(run=None, movements=[], header=HeaderInfo(),
                                    skipped_pages=[2])
    model = build_model(score, recognition)
    assert [p.warnings for p in model.pages] == [["low_resolution"],
                                                 ["low_resolution", "audiveris_skipped"]]
    assert model.pages[0].source_dpi == 72.0


# --- Mesures vides --------------------------------------------------------------------------


def with_empty_measure():
    return model_of([measure("m1", quarters("m1", 4), [treble(), four_four()]),
                     measure("m2", []),
                     measure("m3", quarters("m3", 4))])


def test_an_empty_measure_is_a_question():
    model = with_empty_measure()
    [question], unasked = build_questions(model, validate(model))
    assert unasked == []
    assert question.code == "measure_empty" and question.measure_numbers == [2]
    assert question.measure_id == "m2"
    assert [(c.id, c.label) for c in question.choices] == [
        ("accept", "empty_rest"), ("count", "rest_other_count"), ("repeat", "empty_repeat"),
        ("keep", "empty_has_notes")]
    _, [rest] = question.choices[0].changes()
    assert (rest.measure_id, rest.kind, rest.value) == (
        "m2", "rest", {"duration": "4", "dots": 0, "voice": 1, "full_measure": True})
    # Pause de 8 mesures : un silence, et la pause multiple.
    _, additions = question.choices[1].changes(8)
    assert [(a.kind, a.value.get("count")) for a in additions] == [("rest", None),
                                                                   ("multirest", 8)]
    assert question.choices[3].changes() == ([], [])


@pytest.fixture
def session(conn, tmp_path):
    return QuestionSession(conn, CorrectionService(conn, tmp_path / "extraits"),
                           work_dir=tmp_path / "travail")


def test_answering_a_rest_fills_the_measure(conn, session, score_id):
    save_model(conn, score_id, with_empty_measure())
    [question] = session.state(score_id)["questions"]
    state = session.answer(score_id, question["key"], "accept")
    assert state["questions"] == [] and state["unasked"] == 0
    [rest] = load_model(conn, score_id).parts[0].measures[1].events
    assert rest.kind == "rest" and rest.value["full_measure"]


def test_answering_a_long_rest_renumbers_the_following_measures(conn, session, score_id):
    save_model(conn, score_id, with_empty_measure())
    [question] = session.state(score_id)["questions"]
    session.answer(score_id, question["key"], "count", 8)
    assert [m.number for m in load_model(conn, score_id).parts[0].measures] == [1, 2, 10]


def test_notes_to_add_by_hand_are_not_asked_again(conn, session, score_id):
    save_model(conn, score_id, with_empty_measure())
    [question] = session.state(score_id)["questions"]
    assert session.answer(score_id, question["key"], "keep")["questions"] == []


def test_repeating_the_previous_measure_copies_its_notes_in_order(conn, session, score_id):
    model = model_of([measure("m1", [note("m1.a", "C", 5, "2"), note("m1.b", "E", 5, "2")],
                              [treble(), four_four()]),
                      measure("m2", [])])
    save_model(conn, score_id, model)
    [question] = session.state(score_id)["questions"]
    session.answer(score_id, question["key"], "repeat")
    copied = load_model(conn, score_id).parts[0].measures[1].events
    assert [(s.value["step"], s.value["duration"]) for s in copied] == [("C", "2"), ("E", "2")]


def test_empty_percussion_measures_are_not_asked():
    drums = attribute("c", "clef", sign="percussion", line=None)
    model = model_of([measure("m1", quarters("m1", 4), [drums, four_four()]),
                      measure("m2", [])])
    questions, _ = build_questions(model, validate(model))
    assert all(q.code != "measure_empty" for q in questions)
