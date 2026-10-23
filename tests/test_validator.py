"""Tests du validateur complet : rapport, tri, application des corrections proposées."""

from recomuse.learning.corrections import CorrectionService
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.store import load_model, save_model
from recomuse.validation import apply_fixes, validate

from validation_helpers import four_four, measure, model_of, note, treble


def octave_down_model():
    """Saxophone alto lu avec une clé de sol octaviée peu sûre (erreur d'Audiveris du corpus)."""
    clef = treble("c", octave_change=-1, confidence=0.3)
    return model_of([measure("m1", [note("n1", "B", 3), note("n2", "C", 3), note("n3", "D", 4),
                                    note("n4", "E", 4)], [clef, four_four()]),
                     measure("m2", [note("n5", "F", 4, "4")])],
                    name="Alto Saxophone")


def test_report_orders_issues_and_avoids_duplicates():
    report = validate(octave_down_model())
    assert [i.code for i in report.issues] == ["clef_octave_suspicious"]
    # Le do3 (hors tessiture du saxophone) est déjà couvert par la clé : pas de doublon.
    assert not report.by_code("note_out_of_range")
    data = report.to_dict()
    assert data["counts"] == {"clef_octave_suspicious": 1}
    assert data["issues"][0]["cause"] == "P1:clef_octave_suspicious"


def test_apply_fixes_corrects_the_whole_part_in_one_answer(conn, score_id, tmp_path):
    model = octave_down_model()
    save_model(conn, score_id, model)
    issue = validate(model).issues[0]
    service = CorrectionService(conn, snippets_dir=tmp_path)

    ids = apply_fixes(service, score_id, issue, source="question")

    assert len(ids) == 6                       # la clé et ses 5 notes
    corrected = load_model(conn, score_id)
    assert corrected.find("c")[2].value["octave_change"] == 0
    assert [corrected.find(f"n{k}")[2].value["octave"] for k in range(1, 6)] == [4, 4, 5, 5, 5]
    journal = CorrectionJournal(conn)
    assert len({journal.get(i).group_id for i in ids}) == 1
    assert journal.get(ids[0]).reason == "clef_octave_suspicious"
    # Après correction, plus de problème.
    assert validate(corrected).issues == []


def test_issue_without_fixes_applies_nothing(conn, score_id, tmp_path):
    model = model_of([measure("m1", [note("a", "C", 5)] * 5, [four_four()]),
                      measure("m2", [note("b", "C", 5)] * 1)])
    save_model(conn, score_id, model)
    issue = validate(model).by_code("measure_duration")[0]
    assert apply_fixes(CorrectionService(conn, snippets_dir=tmp_path), score_id, issue) == []
