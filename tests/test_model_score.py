"""Tests du modèle interne : structure, enregistrement en JSON et dans la base."""

import sqlite3
from fractions import Fraction

import pytest

from recomuse.model.score import Measure, PageInfo, Part, ScoreModel, Symbol
from recomuse.model.store import load_model, save_model
from recomuse.storage import database


def note(ident, duration="1", **value):
    return Symbol(id=ident, kind="note", value={"step": "C", "octave": 5, "alter": 0,
                                                 "duration": duration, "voice": 1, "chord": False,
                                                 "grace": False, **value},
                  page=1, bbox=(10.0, 20.0, 15.0, 12.0))


def sample_model() -> ScoreModel:
    m1 = Measure(id="m1", number=0, page=1, expected_duration="2",
                 attributes=[Symbol(id="t", kind="time", value={"beats": 2, "beat_type": 4})],
                 events=[note("n1"), note("n2", chord=True), note("g", "1/2", grace=True),
                         note("n3", "1")])
    m2 = Measure(id="m2", number=0, page=1,
                 attributes=[Symbol(id="mr", kind="multirest", value={"count": 8})])
    m3 = Measure(id="m3", number=0, page=2, events=[note("n4", "2")])
    return ScoreModel(title="Marche d'Acoz", instrument="Bugle", composers=["J. Dupont"],
                      parts=[Part(id="P1", name="Bugle", measures=[m1, m2, m3])],
                      pages=[PageInfo(1, "p1.png", 2480, 3508, "vector")])


def test_renumber_counts_multirests():
    model = sample_model()
    model.renumber()
    assert [m.number for m in model.parts[0].measures] == [1, 2, 10]


def test_measure_duration_ignores_chords_and_grace_notes():
    measure = sample_model().parts[0].measures[0]
    assert measure.duration() == Fraction(2)
    assert measure.symbols()[0].kind == "time"


def test_symbol_duration():
    assert note("x", "3/2").duration == Fraction(3, 2)
    assert Symbol(id="c", kind="clef", value={"sign": "G", "line": 2}).duration is None


def test_find():
    model = sample_model()
    part, measure, symbol = model.find("n3")
    assert (part.id, measure.id, symbol.id) == ("P1", "m1", "n3")
    with pytest.raises(KeyError):
        model.find("absent")


def test_json_round_trip():
    model = sample_model()
    copy = ScoreModel.from_dict(model.to_dict())
    assert copy == model
    assert isinstance(copy.parts[0].measures[0].events[0].bbox, tuple)


def test_save_and_load(conn, score_id):
    model = sample_model()
    save_model(conn, score_id, model)
    assert load_model(conn, score_id) == model

    model.title = "Autre titre"
    save_model(conn, score_id, model)               # remplace l'ancien
    assert load_model(conn, score_id).title == "Autre titre"
    assert conn.execute("SELECT COUNT(*) FROM score_models").fetchone()[0] == 1


def test_load_missing_model(conn, score_id):
    assert load_model(conn, score_id) is None


def test_database_version_1_is_upgraded(tmp_path):
    """Une base créée par la tâche 2 (version 1) reçoit les tables ajoutées depuis."""
    path = tmp_path / "ancienne.sqlite3"
    raw = sqlite3.connect(path)
    raw.executescript(database._read_schema() + "\nPRAGMA user_version = 1;")
    raw.execute("INSERT INTO scores (source_path) VALUES ('a.pdf')")
    raw.commit()
    raw.close()

    conn = database.connect(path)
    assert database.schema_version(conn) == database.SCHEMA_VERSION == 5
    assert conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 1
    save_model(conn, 1, sample_model())
    conn.close()


def test_invalid_json_is_refused(conn, score_id):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO score_models (score_id, model_json) VALUES (?, 'pas du json')",
                     (score_id,))
