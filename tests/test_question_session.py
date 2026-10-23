"""Tests du déroulement des questions (questions/session.py) et de leur image."""

import base64

import cv2
import numpy as np
import pytest

from recomuse.learning.corrections import CorrectionService
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.store import load_model, save_model
from recomuse.questions.images import question_image
from recomuse.questions.session import QuestionError, QuestionSession

from validation_helpers import (
    attribute,
    four_four,
    measure,
    model_of,
    note,
    page_image,
    rest,
    treble,
)

KEY = "time_signature_missed:P1:m2,m3,m4,m5"


def quarters(ident: str, count: int):
    return [note(f"{ident}.n{k}", "C", 5, "1") for k in range(count)]


@pytest.fixture
def stored(conn, score_id, tmp_path):
    """Une mesure en 4/4 puis quatre mesures de 3 temps (chiffrage 3/4 manqué), sur une
    page dont l'image existe."""
    image = page_image(tmp_path / "page-001.png")
    measures = [measure("m1", quarters("m1", 4), [treble(), four_four()],
                        bbox=(100.0, 160.0, 400.0, 160.0))]
    measures += [measure(f"m{k}", quarters(f"m{k}", 3), bbox=(100.0 + 300 * k, 160.0, 300.0,
                                                                160.0))
                 for k in range(2, 6)]
    model = model_of(measures, image=image)
    save_model(conn, score_id, model)
    return model


@pytest.fixture
def session(conn, tmp_path):
    return QuestionSession(conn, CorrectionService(conn, tmp_path / "extraits"),
                           work_dir=tmp_path / "travail")


def test_state_lists_questions_with_their_image(session, score_id, stored):
    state = session.state(score_id)
    assert state["score_id"] == score_id
    assert [q["key"] for q in state["questions"]] == [KEY]
    assert state["answered"] == 0 and state["can_undo"] is False
    assert state["questions"][0]["image"].startswith("data:image/png;base64,")


def test_answer_applies_the_correction_and_removes_the_question(conn, session, score_id,
                                                                stored):
    state = session.answer(score_id, KEY, "accept")
    assert state["questions"] == []
    assert state["answered"] == 1 and state["can_undo"] is True
    model = load_model(conn, score_id)
    second = model.parts[0].measures[1]
    assert [(s.kind, s.value) for s in second.attributes] == [
        ("time", {"beats": 3, "beat_type": 4})]
    entry = CorrectionJournal(conn).list_for_score(score_id)[0]
    assert entry.source == "question" and entry.reason == "time_signature_missed"


def test_keeping_the_reading_is_remembered(conn, session, score_id, stored):
    """« Non, le chiffrage ne change pas » : rien n'est corrigé, mais la question n'est
    plus posée, même par une autre session (après un redémarrage du logiciel)."""
    state = session.answer(score_id, KEY, "keep")
    assert state["questions"] == []
    assert CorrectionJournal(conn).count() == 0
    assert QuestionSession(conn).state(score_id)["questions"] == []


def test_undo_reverts_the_corrections_and_asks_again(conn, session, score_id, stored):
    session.answer(score_id, KEY, "accept")
    state = session.undo(score_id)
    assert [q["key"] for q in state["questions"]] == [KEY]
    assert state["answered"] == 0 and state["can_undo"] is False
    assert load_model(conn, score_id).parts[0].measures[1].attributes == []
    with pytest.raises(QuestionError):
        session.undo(score_id)


def test_wrong_answers_are_refused(session, score_id, stored):
    with pytest.raises(QuestionError):
        session.answer(score_id, "inconnue", "accept")
    with pytest.raises(QuestionError):
        session.answer(score_id, KEY, "choix-absent")
    with pytest.raises(QuestionError):
        session.state(score_id + 50)


def test_question_image_crops_and_circles():
    page = np.full((400, 600), 255, np.uint8)
    url = question_image(page, (100, 100, 200, 100), [(150, 120, 20, 20)])
    data = base64.b64decode(url.split(",", 1)[1])
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape == (100, 200, 3)
    # Le cadre orange est dessiné autour du symbole (bord gauche du cadre : x = 50 - 6).
    blue, _, red = image[40, 44]
    assert red > 200 and blue < 50
    assert tuple(image[5, 5]) == (255, 255, 255)

    wide = question_image(np.full((400, 3000), 255, np.uint8), (0, 0, 3000, 300), [],
                          max_width=1000)
    small = cv2.imdecode(np.frombuffer(base64.b64decode(wide.split(",", 1)[1]), np.uint8),
                         cv2.IMREAD_GRAYSCALE)
    assert small.shape == (100, 1000)
    with pytest.raises(ValueError):
        question_image(page, (700, 700, 10, 10), [])


def test_parts_of_a_piece_are_compared(conn, tmp_path):
    """Trois parties d'un même morceau : celle dont la pause de 4 mesures a été lue comme
    une seule mesure reçoit la question « est-ce une pause de 4 mesures ? »."""
    def part(name: str, rest_count: int):
        rest_measure = (measure(f"{name}.m2", [], [attribute(f"{name}.mr", "multirest",
                                                             count=rest_count)])
                        if rest_count > 1 else
                        measure(f"{name}.m2", [rest(f"{name}.r", "4", full=True)]))
        return model_of([measure(f"{name}.m1", quarters(f"{name}.m1", 4),
                                 [treble(f"{name}.c"), four_four(f"{name}.t")]),
                         rest_measure,
                         measure(f"{name}.m3", quarters(f"{name}.m3", 4)),
                         measure(f"{name}.m4", quarters(f"{name}.m4", 4))], name=name)

    ids = {}
    for name, count in [("flute", 4), ("clarinette", 1), ("trompette", 4)]:
        model = part(name, count)
        model.title = "Marche d'Acoz"
        with conn:
            cursor = conn.execute("INSERT INTO scores (title, source_path) VALUES (?, ?)",
                                  (model.title, f"{name}.pdf"))
        ids[name] = cursor.lastrowid
        save_model(conn, cursor.lastrowid, model)

    session = QuestionSession(conn, work_dir=tmp_path / "travail")
    state = session.state(ids["clarinette"])
    assert state["compared_parts"] == 2
    [question] = state["questions"]
    assert question["code"] == "part_measures_missing"
    assert question["key"] == "multirest:P1:clarinette.m2"
    assert question["params"]["count"] == 4
    session.answer(ids["clarinette"], question["key"], "accept")
    assert sum(m.length for m in load_model(conn, ids["clarinette"]).parts[0].measures) == 7
    assert session.state(ids["flute"])["questions"] == []


def test_unasked_issues_are_listed_as_checks(conn, score_id, tmp_path):
    """Une mesure au compte faux, sans explication : pas de question, mais un passage à
    vérifier, avec sa mesure et sa page."""
    model = model_of([measure("m1", quarters("m1", 4), [treble(), four_four()]),
                      measure("m2", quarters("m2", 3)),
                      measure("m3", quarters("m3", 4))])
    save_model(conn, score_id, model)
    state = QuestionSession(conn, work_dir=tmp_path / "travail").state(score_id)
    assert state["questions"] == [] and state["unasked"] == 1
    assert state["checks"] == [{"code": "measure_duration", "measure_numbers": [2],
                                "measure_id": "m2", "page": 1,
                                "details": {"read": "3", "expected": "4"}}]


def test_questions_name_their_measure(session, score_id, stored):
    [question] = session.state(score_id)["questions"]
    assert question["measure_id"] == "m2" and question["page"] == 1
