"""Tests des règles apprises et de la mémoire des partitions (learning/)."""

import json

import numpy as np
import pytest

from recomuse import library
from recomuse.api import Api
from recomuse.learning import memory, rules
from recomuse.learning.corrections import CorrectionService, NewSymbol
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.store import load_model, save_model
from recomuse.questions.session import QuestionSession
from recomuse.recognition import tools
from recomuse.recognition.tools import ToolsStatus
from recomuse.validation.issues import Issue

from synthetic import part_pdf
from validation_helpers import four_four, measure, model_of, note, treble

KEY = "time_signature_missed:P1:m2,m3,m4,m5"


def quarters(ident: str, count: int):
    return [note(f"{ident}.n{k}", "C", 5, "1") for k in range(count)]


def three_four_model():
    """Une mesure en 4/4, puis quatre mesures de 3 temps : le chiffrage 3/4 a été manqué."""
    measures = [measure("m1", quarters("m1", 4), [treble(), four_four()])]
    measures += [measure(f"m{k}", quarters(f"m{k}", 3)) for k in range(2, 6)]
    return model_of(measures)


def new_score(conn) -> int:
    with conn:
        cursor = conn.execute("INSERT INTO scores (title, source_path) VALUES (?, ?)",
                              (None, f"partie-{np.random.randint(1e9)}.pdf"))
    save_model(conn, cursor.lastrowid, three_four_model())
    return cursor.lastrowid


@pytest.fixture
def session(conn, tmp_path):
    return QuestionSession(conn, CorrectionService(conn, tmp_path / "extraits"),
                           work_dir=tmp_path / "travail")


# --- Signatures ---------------------------------------------------------------------------


def test_signatures():
    model = three_four_model()
    sig = rules.issue_signature
    assert sig(model, Issue("clef_octave_suspicious", "P1", [1],
                            details={"octave_change": -1})) == {
        "code": "clef_octave_suspicious", "octave_change": -1}
    assert sig(model, Issue("note_position_mismatch", "P1", [1],
                            details={"position": 11, "read": "C5", "from_position": "C6"})) == {
        "code": "note_position_mismatch", "place": "above", "shift": "octave"}
    assert sig(model, Issue("note_position_mismatch", "P1", [1],
                            details={"position": 4, "read": "C5", "from_position": "D5"}))[
        "shift"] == "other"
    assert sig(model, Issue("multirest_missed", "P1", [1], details={"count": None}))[
        "count_read"] is False
    assert sig(model, Issue("multirest_count_unknown", "P1", [1])) is None
    assert rules.signature_key({"b": 1, "a": "é"}) == '{"a": "é", "b": 1}'


# --- Règles -------------------------------------------------------------------------------


def test_rule_is_learned_after_three_identical_answers(conn, session):
    for _ in range(2):
        session.answer(new_score(conn), KEY, "accept")
    assert rules.learned_rules(conn) == []                  # 2 réponses : pas encore
    session.answer(new_score(conn), KEY, "accept")
    [rule] = rules.learned_rules(conn)
    assert rule.signature == {"code": "time_signature_missed"}
    assert (rule.choice_id, rule.choice_label, rule.evidence, rule.agreeing, rule.enabled) == (
        "accept", "time_is", 3, 3, True)

    # La partition suivante reçoit la réponse sans que la question soit posée.
    fourth = new_score(conn)
    state = session.state(fourth)
    assert state["questions"] == [] and state["answered_by_rules"] == 1
    second = load_model(conn, fourth).parts[0].measures[1]
    assert [(s.kind, s.source) for s in second.attributes] == [("time", "rule")]
    entry = CorrectionJournal(conn).list_for_score(fourth)[0]
    assert entry.source == "rule" and entry.reason == "rule:time_signature_missed"

    # Annuler la réponse de la règle : la question est posée à l'utilisateur.
    state = session.undo(fourth)
    assert [q["key"] for q in state["questions"]] == [KEY]
    assert load_model(conn, fourth).parts[0].measures[1].attributes == []


def test_one_score_is_not_enough(conn, session):
    """Trois réponses identiques sur une seule partition ne font pas une règle."""
    score = new_score(conn)
    with conn:
        for k in range(3):
            conn.execute(
                "INSERT INTO question_answers (score_id, question_key, code, choice_id,"
                " correction_ids, signature, choice_label) VALUES (?, ?, ?, ?, '[]', ?, ?)",
                (score, f"q{k}", "clef_octave_suspicious", "accept",
                 '{"code": "clef_octave_suspicious", "octave_change": -1}', "clef_plain"))
    assert rules.learned_rules(conn) == []


def test_contrary_answers_and_disabled_rules(conn, session):
    for _ in range(3):
        session.answer(new_score(conn), KEY, "accept")
    key = rules.learned_rules(conn)[0].key
    rules.set_enabled(conn, key, False)
    assert rules.learned_rules(conn)[0].enabled is False
    assert rules.rule_for(conn, key) is None
    assert session.state(new_score(conn))["questions"] != []    # règle désactivée
    rules.set_enabled(conn, key, True)
    # Une réponse contraire : 3 sur 4, moins de 90 % → plus de règle.
    other = new_score(conn)
    rules.set_enabled(conn, key, False)
    session.answer(other, KEY, "keep")
    assert rules.learned_rules(conn) == []
    with pytest.raises(ValueError):
        rules.set_enabled(conn, "pas du json", True)


def test_api_rules(conn, session):
    for _ in range(3):
        session.answer(new_score(conn), KEY, "keep")
    api = Api(conn, ":memory:")
    [rule] = api.get_rules()
    assert rule["choice_id"] == "keep" and rule["signature"]["code"] == "time_signature_missed"
    result = api.set_rule_enabled(rule["key"], False)
    assert result["rules"][0]["enabled"] is False
    assert api.set_rule_enabled("pas du json", True) == {"error": "unexpected"}


# --- Mémoire des partitions ---------------------------------------------------------------


def test_fingerprints():
    rng = np.random.default_rng(1)
    page = (rng.random((1000, 700)) * 255).astype(np.uint8)
    same = page.copy()
    same[10:20, 10:20] = 0                                   # petite tache : même page
    other = (rng.random((1000, 700)) * 255).astype(np.uint8)
    a, b, c = memory.fingerprint(page), memory.fingerprint(same), memory.fingerprint(other)
    assert len(a) == 64
    assert memory.distance(a, b) <= memory.MAX_DISTANCE < memory.distance(a, c)


def test_replay_corrections_and_answers(conn, session):
    """Corrections (changement, ajout, suppression) et réponses d'une partition rejouées
    sur une nouvelle lecture des mêmes pages."""
    old = new_score(conn)
    service = CorrectionService(conn)
    session.answer(old, KEY, "accept")                       # ajout du chiffrage 3/4
    service.apply(old, "m1.n0", {"octave": 6}, source="manual")
    service.apply_group(old, [], source="manual", removals=["m2.n2"],
                        additions=[NewSymbol("m3", "note", {"step": "E", "octave": 5,
                                                            "duration": "1"}, after="m3.n0")])
    undone = service.apply(old, "m1.n1", {"octave": 3}, source="manual")
    service.revert(undone)                                   # annulée : pas rejouée

    new = new_score(conn)
    result = memory.replay(conn, service, old, new)
    assert result == {"from": old, "applied": 4, "skipped": 0, "answers": 1}
    model = load_model(conn, new)
    assert model.find("m1.n0")[2].value["octave"] == 6
    assert model.find("m1.n1")[2].value["octave"] == 5
    assert [s.id for s in model.find_measure("m3")[1].events] == [
        "m3.n0", "m3.note+0", "m3.n1", "m3.n2"]
    assert [s.id for s in model.find_measure("m2")[1].events] == ["m2.n0", "m2.n1"]
    assert model.find_measure("m2")[1].attributes[0].kind == "time"
    assert all(c.source == "rule" and c.reason == f"memory:{old}"
               for c in CorrectionJournal(conn).list_for_score(new))
    state = session.state(new)
    assert state["questions"] == [] and state["answered_by_memory"] == 1
    # La réponse reprise s'annule comme une autre : ses corrections partent avec elle.
    state = session.undo(new)
    assert state["answered_by_memory"] == 0
    assert load_model(conn, new).find_measure("m2")[1].attributes == []


def test_replay_skips_what_no_longer_exists(conn):
    service = CorrectionService(conn)
    old = new_score(conn)
    service.apply(old, "m1.n0", {"octave": 6}, source="manual")
    new = new_score(conn)
    model = load_model(conn, new)
    model.parts[0].measures[0].events.pop(0)                 # la lecture a changé
    save_model(conn, new, model)
    assert memory.replay(conn, service, old, new) == {"from": old, "applied": 0,
                                                      "skipped": 1, "answers": 0}


def test_opening_the_same_file_again_reuses_the_corrections(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "check_tools", lambda: ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[], missing_languages=[]))
    pdf = part_pdf(tmp_path / "marche.pdf")
    [first] = library.open_file(conn, pdf, work_root=tmp_path / "travail")
    assert "memory" not in first
    # La partie de test n'a que des mesures (pas de police musicale) : on y ajoute une pause.
    measure_id = load_model(conn, first["score_id"]).parts[0].measures[2].id
    CorrectionService(conn).apply_group(first["score_id"], [], source="manual", additions=[
        NewSymbol(measure_id, "multirest", {"count": 4})])

    # Le même PDF, sous un autre nom.
    copy = tmp_path / "copie de marche.pdf"
    copy.write_bytes(pdf.read_bytes())
    [second] = library.open_file(conn, copy, work_root=tmp_path / "travail")
    assert second["memory"]["from"] == first["score_id"]
    assert second["memory"]["applied"] == 1 and second["memory"]["read_at"]
    again = load_model(conn, second["score_id"]).find_measure(measure_id)[1]
    assert [(s.kind, s.value) for s in again.attributes] == [("multirest", {"count": 4})]
    assert second["measure_count"] == first["measure_count"] + 3
    stored = conn.execute("SELECT COUNT(*) FROM page_fingerprints").fetchone()[0]
    assert stored == 2
    json.dumps(second)                                       # tout passe vers l'interface
