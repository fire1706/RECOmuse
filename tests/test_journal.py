"""Tests du journal des corrections."""

import sqlite3

import pytest

from recomuse.learning.journal import BoundingBox, Correction, CorrectionJournal


@pytest.fixture
def journal(conn):
    return CorrectionJournal(conn)


def make_octave_fix(score_id: int) -> Correction:
    """Exemple tiré du test de faisabilité : un do6 lu do5 par Audiveris."""
    return Correction(
        score_id=score_id,
        page_number=1,
        measure_number=12,
        staff_number=1,
        symbol_id="p1-m12-n3",
        symbol_kind="note",
        bbox=BoundingBox(x=812.0, y=140.5, width=22.0, height=18.0),
        snippet_path="score1/p1-m12-n3.png",
        old_value={"step": "C", "octave": 5},
        new_value={"step": "C", "octave": 6},
        confidence=0.42,
        alternatives=[{"step": "C", "octave": 5}, {"step": "C", "octave": 6}],
        source="question",
        group_id="q-octave-1",
        reason="octave_above_staff",
    )


def test_record_and_read_back_all_fields(journal, score_id):
    original = make_octave_fix(score_id)
    correction_id = journal.record(original)

    stored = journal.get(correction_id)
    assert stored is not None
    assert stored.id == correction_id
    assert stored.created_at  # rempli automatiquement par la base
    # Hormis id et created_at, tout doit être identique à ce qui a été enregistré.
    for field_name in (
        "score_id", "page_number", "measure_number", "staff_number", "symbol_id",
        "symbol_kind", "bbox", "snippet_path", "old_value", "new_value",
        "confidence", "alternatives", "source", "group_id", "reason", "reverts_id",
    ):
        assert getattr(stored, field_name) == getattr(original, field_name), field_name


def test_get_unknown_correction_returns_none(journal):
    assert journal.get(12345) is None


def test_list_for_score_keeps_order(journal, score_id):
    first = journal.record(make_octave_fix(score_id))
    second = journal.record(
        Correction(score_id=score_id, symbol_kind="time_signature",
                   old_value="4/4", new_value="3/4", source="manual")
    )
    assert [c.id for c in journal.list_for_score(score_id)] == [first, second]
    assert journal.count() == 2


def test_journal_rows_cannot_be_modified(conn, journal, score_id):
    correction_id = journal.record(make_octave_fix(score_id))
    with pytest.raises(sqlite3.IntegrityError, match="ajout seul"):
        conn.execute("UPDATE corrections SET new_value = '\"D6\"' WHERE id = ?", (correction_id,))


def test_journal_rows_cannot_be_deleted(conn, journal, score_id):
    correction_id = journal.record(make_octave_fix(score_id))
    with pytest.raises(sqlite3.IntegrityError, match="ajout seul"):
        conn.execute("DELETE FROM corrections WHERE id = ?", (correction_id,))


def test_score_with_corrections_cannot_be_deleted(conn, journal, score_id):
    journal.record(make_octave_fix(score_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM scores WHERE id = ?", (score_id,))


def test_revert_records_the_inverse_correction(journal, score_id):
    correction_id = journal.record(make_octave_fix(score_id))
    revert_id = journal.revert(correction_id)

    revert = journal.get(revert_id)
    assert revert.source == "revert"
    assert revert.reverts_id == correction_id
    assert revert.old_value == {"step": "C", "octave": 6}
    assert revert.new_value == {"step": "C", "octave": 5}
    assert revert.symbol_id == "p1-m12-n3"
    # L'original est toujours là, intact.
    assert journal.get(correction_id).new_value == {"step": "C", "octave": 6}


def test_revert_of_an_added_symbol_stores_null(journal, score_id):
    """Un symbole ajouté (pas d'ancienne valeur) : l'annuler revient à le supprimer."""
    added = journal.record(
        Correction(score_id=score_id, symbol_kind="rest", new_value={"duration": "quarter"},
                   source="manual")
    )
    revert = journal.get(journal.revert(added))
    assert revert.new_value is None
    assert revert.old_value == {"duration": "quarter"}


def test_revert_unknown_correction_raises(journal):
    with pytest.raises(KeyError):
        journal.revert(999)


def test_revert_source_requires_reverts_id(journal):
    with pytest.raises(ValueError):
        journal.record(Correction(symbol_kind="note", new_value="C5", source="revert"))


def test_reverts_id_only_allowed_for_revert(journal, score_id):
    correction_id = journal.record(make_octave_fix(score_id))
    with pytest.raises(ValueError):
        journal.record(Correction(symbol_kind="note", new_value="C5", source="manual",
                                  reverts_id=correction_id))


def test_already_recorded_correction_is_refused(journal, score_id):
    stored = journal.get(journal.record(make_octave_fix(score_id)))
    with pytest.raises(ValueError):
        journal.record(stored)


def test_invalid_source_is_refused_by_database(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO corrections (symbol_kind, new_value, source) "
            "VALUES ('note', '\"C5\"', 'magic')"
        )


def test_confidence_must_be_between_0_and_1(journal):
    with pytest.raises(sqlite3.IntegrityError):
        journal.record(Correction(symbol_kind="note", new_value="C5", source="manual",
                                  confidence=1.5))


def test_accents_are_kept(journal):
    correction_id = journal.record(
        Correction(symbol_kind="text", old_value="Euphonlum", new_value="Euphonium sib — 1ère",
                   source="manual")
    )
    assert journal.get(correction_id).new_value == "Euphonium sib — 1ère"
