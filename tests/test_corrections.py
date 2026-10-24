"""Tests du service unique de corrections (journal + modèle, dans une seule transaction)."""

import sqlite3

import numpy as np
import pytest

from recomuse.importer.loading import read_gray, write_png
from recomuse.learning.corrections import CorrectionError, CorrectionService
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.score import Measure, PageInfo, Part, ScoreModel, Symbol
from recomuse.model.store import load_model, save_model


@pytest.fixture
def page_image(tmp_path):
    path = tmp_path / "page-001.png"
    write_png(path, np.full((1000, 800), 255, np.uint8))
    return path


@pytest.fixture
def service(conn, tmp_path):
    return CorrectionService(conn, snippets_dir=tmp_path / "extraits")


@pytest.fixture
def stored(conn, score_id, page_image):
    """Partition d'une mesure : un do5 lu « do5 » alors que c'est un do6 (cas du test de
    faisabilité), et un chiffrage."""
    note = Symbol(id="n1", kind="note", page=1, bbox=(400.0, 300.0, 25.0, 20.0), confidence=0.4,
                  alternatives=[{"octave": 6}], source="audiveris",
                  value={"step": "C", "octave": 5, "alter": 0, "duration": "1", "voice": 1,
                         "chord": False, "grace": False})
    other = Symbol(id="n2", kind="note", page=1, bbox=(450.0, 300.0, 25.0, 20.0),
                   value={"step": "D", "octave": 5, "alter": 0, "duration": "1", "voice": 1,
                          "chord": False, "grace": False})
    time = Symbol(id="t1", kind="time", page=1, bbox=None, value={"beats": 4, "beat_type": 4})
    model = ScoreModel(parts=[Part(id="P1", measures=[
        Measure(id="m1", number=12, page=1, attributes=[time], events=[note, other])])],
        pages=[PageInfo(1, str(page_image), 800, 1000)])
    save_model(conn, score_id, model)
    return model


def test_apply_updates_model_and_journal(conn, service, score_id, stored, tmp_path):
    correction_id = service.apply(score_id, "n1", {"octave": 6}, source="question",
                                  reason="octave_above_staff")

    symbol = load_model(conn, score_id).find("n1")[2]
    assert symbol.value["octave"] == 6 and symbol.value["step"] == "C"
    assert symbol.source == "user" and symbol.confidence == 1.0

    entry = CorrectionJournal(conn).get(correction_id)
    assert entry.old_value["octave"] == 5 and entry.new_value["octave"] == 6
    assert entry.measure_number == 12 and entry.page_number == 1
    assert entry.confidence == 0.4                      # confiance AVANT la correction
    assert entry.alternatives == [{"octave": 6}]
    assert entry.reason == "octave_above_staff"
    assert entry.bbox.x == 400.0
    # Extrait d'image découpé autour du symbole, gardé avec la correction.
    snippet = tmp_path / "extraits" / entry.snippet_path
    assert snippet.is_file()
    assert read_gray(snippet).shape == (20 + 2 * 60, 25 + 2 * 60)


def test_group_shares_one_group_id(conn, service, score_id, stored):
    ids = service.apply_group(score_id, [("n1", {"octave": 6}), ("n2", {"octave": 6})],
                              source="question")
    journal = CorrectionJournal(conn)
    groups = {journal.get(i).group_id for i in ids}
    assert len(groups) == 1 and None not in groups
    model = load_model(conn, score_id)
    assert [model.find(s)[2].value["octave"] for s in ("n1", "n2")] == [6, 6]


def test_group_is_all_or_nothing(conn, service, score_id, stored):
    with pytest.raises(CorrectionError):
        service.apply_group(score_id, [("n1", {"octave": 6}), ("absent", {"octave": 6})],
                            source="question")
    assert CorrectionJournal(conn).count() == 0
    assert load_model(conn, score_id).find("n1")[2].value["octave"] == 5


def test_database_error_leaves_nothing(conn, service, score_id, stored):
    """Si l'écriture du journal échoue (ici : source refusée par la base), le modèle ne
    change pas non plus."""
    with pytest.raises(sqlite3.IntegrityError):
        service.apply(score_id, "n1", {"octave": 6}, source="magie")
    assert CorrectionJournal(conn).count() == 0
    assert load_model(conn, score_id).find("n1")[2].value["octave"] == 5


def test_unknown_field_is_refused(service, score_id, stored):
    with pytest.raises(CorrectionError):
        service.apply(score_id, "n1", {"couleur": "bleu"}, source="manual")


def test_declared_field_can_be_added(conn, service, score_id, stored):
    service.apply(score_id, "n1", {"tuplet": [3, 2]}, source="manual")
    assert load_model(conn, score_id).find("n1")[2].value["tuplet"] == [3, 2]


def test_revert_restores_the_old_value(conn, service, score_id, stored):
    correction_id = service.apply(score_id, "n1", {"octave": 6}, source="question")
    revert_id = service.revert(correction_id)

    assert load_model(conn, score_id).find("n1")[2].value["octave"] == 5
    journal = CorrectionJournal(conn)
    assert journal.get(revert_id).reverts_id == correction_id
    assert journal.count() == 2                         # le journal garde tout


def test_history(service, score_id, stored):
    service.apply(score_id, "n1", {"octave": 6}, source="question")
    service.apply(score_id, "n2", {"step": "E"}, source="manual")
    service.apply(score_id, "n1", {"alter": 1}, source="manual")
    history = service.history(score_id, "n1")
    assert [(c.old_value["octave"], c.new_value["octave"], c.new_value["alter"]) for c in history] \
        == [(5, 6, 0), (6, 6, 1)]


def test_symbol_without_position_has_no_snippet(conn, service, score_id, stored):
    correction_id = service.apply(score_id, "t1", {"beats": 3}, source="validator")
    entry = CorrectionJournal(conn).get(correction_id)
    assert entry.snippet_path is None
    assert load_model(conn, score_id).find("t1")[2].source == "validator"


def test_missing_model_or_symbol(service, score_id, stored):
    with pytest.raises(CorrectionError):
        service.apply(score_id, "absent", {"octave": 6}, source="question")
    with pytest.raises(CorrectionError):
        service.apply(score_id + 99, "n1", {"octave": 6}, source="question")
    with pytest.raises(CorrectionError):
        service.revert(1234)


def test_revert_source_is_reserved(service, score_id, stored):
    with pytest.raises(ValueError):
        service.apply(score_id, "n1", {"octave": 6}, source="revert")


@pytest.fixture
def two_measures(conn, score_id, page_image):
    """Deux mesures en 4/4 : la 1re est un silence qui était en fait une pause de 8."""
    rest = Symbol(id="r1", kind="rest", page=1, value={"duration": "4", "full_measure": True})
    time = Symbol(id="t1", kind="time", page=1, value={"beats": 4, "beat_type": 4})
    clef = Symbol(id="c1", kind="clef", page=1, value={"sign": "G", "line": 2})
    model = ScoreModel(parts=[Part(id="P1", measures=[
        Measure(id="m1", number=1, page=1, bbox=(100.0, 200.0, 300.0, 120.0),
                attributes=[clef, time], events=[rest], expected_duration="4"),
        Measure(id="m2", number=2, page=1, expected_duration="4")])],
        pages=[PageInfo(1, str(page_image), 800, 1000)])
    save_model(conn, score_id, model)
    return model


def test_added_symbol_is_journaled_and_numbering_follows(conn, service, score_id, two_measures):
    from recomuse.learning.corrections import NewSymbol

    ids = service.apply_group(score_id, [], source="question", reason="multirest_missed",
                              additions=[NewSymbol("m1", "multirest", {"count": 8})])
    model = load_model(conn, score_id)
    first, second = model.parts[0].measures
    assert [s.kind for s in first.attributes] == ["clef", "time", "multirest"]
    added = first.attributes[2]
    assert added.id == "m1.multirest+0" and added.source == "user"
    assert added.bbox == (100.0, 200.0, 120.0, 120.0)     # début de la mesure
    assert second.number == 9                             # la pause compte 8 mesures
    entry = CorrectionJournal(conn).get(ids[0])
    assert entry.old_value is None and entry.new_value == {"count": 8}
    assert entry.symbol_kind == "multirest" and entry.snippet_path is not None


def test_added_time_signature_changes_the_expected_durations(conn, service, score_id,
                                                             two_measures):
    from recomuse.learning.corrections import NewSymbol

    service.apply_group(score_id, [], source="question",
                        additions=[NewSymbol("m2", "time", {"beats": 3, "beat_type": 4})])
    first, second = load_model(conn, score_id).parts[0].measures
    assert [s.kind for s in second.attributes] == ["time"]
    assert (first.expected_duration, second.expected_duration) == ("4", "3")


def test_reverting_an_addition_removes_the_symbol(conn, service, score_id, two_measures):
    from recomuse.learning.corrections import NewSymbol

    ids = service.apply_group(score_id, [("t1", {"beats": 2})], source="question",
                              additions=[NewSymbol("m1", "multirest", {"count": 8})])
    service.revert_all(ids)
    first, second = load_model(conn, score_id).parts[0].measures
    assert [s.kind for s in first.attributes] == ["clef", "time"]
    assert first.attributes[1].value["beats"] == 4
    assert second.number == 2
    assert CorrectionJournal(conn).count() == 4           # 2 corrections, 2 annulations


def test_impossible_additions_are_refused(conn, service, score_id, two_measures):
    from recomuse.learning.corrections import NewSymbol

    for addition in [NewSymbol("absente", "multirest", {"count": 2}),
                     NewSymbol("m1", "time", {"beats": 3, "beat_type": 4}),   # déjà un chiffrage
                     NewSymbol("m1", "slur", {}),
                     NewSymbol("m1", "note", {"step": "C"}, after="absent"),
                     NewSymbol("m1", "multirest", {"nombre": 2})]:
        with pytest.raises(CorrectionError):
            service.apply_group(score_id, [], source="question", additions=[addition])
    with pytest.raises(CorrectionError):        # deux pauses dans la même réponse
        service.apply_group(score_id, [], source="question",
                            additions=[NewSymbol("m2", "multirest", {"count": 2})] * 2)
    assert CorrectionJournal(conn).count() == 0


def test_revert_restores_confidence_and_origin(conn, service, score_id, stored):
    """Après annulation, la note redevient « lue par Audiveris, peu sûre » : le validateur
    la vérifie de nouveau."""
    model = load_model(conn, score_id)
    model.pages[0].source = "audiveris"
    save_model(conn, score_id, model)
    first = service.apply(score_id, "n1", {"octave": 6}, source="question")
    second = service.apply(score_id, "n1", {"alter": 1}, source="manual")
    service.revert(second)
    note = load_model(conn, score_id).find("n1")[2]
    assert (note.source, note.value["alter"]) == ("user", 0)   # la 1re correction tient
    service.revert(first)
    note = load_model(conn, score_id).find("n1")[2]
    assert (note.source, note.confidence, note.value["octave"]) == ("audiveris", 0.4, 5)


def test_removing_and_adding_notes_and_undoing(conn, service, score_id, stored):
    """Une note lue en trop est supprimée, une note oubliée ajoutée ; l'annulation remet
    tout comme avant, la note supprimée à sa place exacte."""
    from recomuse.learning.corrections import NewSymbol

    value = {"step": "E", "octave": 5, "alter": 0, "duration": "1", "voice": 1}
    ids = service.apply_group(score_id, [], source="manual", removals=["n1"],
                              additions=[NewSymbol("m1", "note", value, after="n2")])
    events = load_model(conn, score_id).parts[0].measures[0].events
    assert [s.id for s in events] == ["n2", "m1.note+0"]
    journal = CorrectionJournal(conn)
    removal, addition = (journal.get(i) for i in ids)
    assert removal.new_value is None and removal.old_value["octave"] == 5
    assert removal.location == {"measure_id": "m1", "list": "events", "index": 0}
    assert addition.location == {"measure_id": "m1", "list": "events", "index": 1}
    assert addition.bbox.x == 450.0                     # à la place de la note qui précède

    service.revert_all(ids)
    events = load_model(conn, score_id).parts[0].measures[0].events
    assert [s.id for s in events] == ["n1", "n2"]
    restored = events[0]
    assert restored.value["octave"] == 5 and restored.bbox == (400.0, 300.0, 25.0, 20.0)
    assert restored.confidence == 0.4

    # Ajout au début de la mesure ; un symbole ne peut pas être corrigé et supprimé.
    service.apply_group(score_id, [], source="manual",
                        additions=[NewSymbol("m1", "rest", {"duration": "1"})])
    assert load_model(conn, score_id).parts[0].measures[0].events[0].kind == "rest"
    with pytest.raises(CorrectionError):
        service.apply_group(score_id, [("n2", {"octave": 4})], source="manual",
                            removals=["n2"])
