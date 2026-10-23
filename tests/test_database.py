"""Tests de la création et de la mise à jour du schéma de la base."""

import sqlite3

import pytest

from recomuse import paths
from recomuse.storage import database


def test_new_database_gets_current_schema_version(conn):
    assert database.schema_version(conn) == database.SCHEMA_VERSION


def test_expected_tables_exist(conn):
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"scores", "corrections"} <= tables


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO corrections (score_id, symbol_kind, new_value, source) "
            "VALUES (999, 'note', '\"C5\"', 'manual')"
        )


def test_reopening_a_database_keeps_its_data(tmp_path):
    db_file = tmp_path / "base.sqlite3"
    first = database.connect(db_file)
    with first:
        first.execute("INSERT INTO scores (source_path) VALUES ('a.pdf')")
    first.close()

    # La seconde ouverture ne doit pas recréer le schéma (ce qui échouerait) ni perdre de données.
    second = database.connect(db_file)
    assert second.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 1
    second.close()


def test_database_from_newer_version_is_refused(tmp_path):
    db_file = tmp_path / "future.sqlite3"
    raw = sqlite3.connect(db_file)
    raw.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
    raw.close()

    with pytest.raises(database.DatabaseTooNewError):
        database.connect(db_file)


def test_default_database_goes_to_data_dir(isolated_data_dir):
    conn = database.connect()
    conn.close()
    assert (isolated_data_dir / paths.DATABASE_FILENAME).is_file()


def test_snippets_dir_is_created(isolated_data_dir):
    assert paths.snippets_dir() == isolated_data_dir / paths.SNIPPETS_DIRNAME
    assert paths.snippets_dir().is_dir()
