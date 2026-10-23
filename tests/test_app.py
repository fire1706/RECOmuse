"""Tests du point d'entrée et du pont Python ↔ interface (sans ouvrir de fenêtre)."""

import sys

from recomuse import __version__, app
from recomuse.api import Api
from recomuse.learning.journal import Correction, CorrectionJournal


def test_ping(conn):
    assert Api(conn, ":memory:").ping() == "pong"


def test_get_app_info(conn):
    CorrectionJournal(conn).record(Correction(symbol_kind="note", new_value="C5", source="manual"))

    info = Api(conn, "chemin/base.sqlite3").get_app_info()
    assert info["version"] == __version__
    assert info["python_version"].startswith("3.12")
    assert info["platform"] == sys.platform
    assert info["database_path"] == "chemin/base.sqlite3"
    assert info["correction_count"] == 1


def test_api_hides_private_attributes(conn):
    """pywebview n'expose que les noms publics : la connexion à la base doit rester privée."""
    public = [name for name in dir(Api(conn, "")) if not name.startswith("_")]
    assert sorted(public) == ["get_app_info", "ping"]


def test_dev_mode_uses_vite_server():
    assert app.resolve_ui_entry(dev=True) == (app.DEV_SERVER_URL, None)


def test_built_ui_is_used_when_present(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    url, html = app.resolve_ui_entry(dev=False, dist_dir=tmp_path)
    assert url == str(tmp_path / "index.html")
    assert html is None


def test_fallback_page_when_ui_not_built(tmp_path):
    url, html = app.resolve_ui_entry(dev=False, dist_dir=tmp_path)
    assert url is None
    assert "npm run build" in html


def test_parse_args():
    assert app.parse_args([]).dev is False
    assert app.parse_args(["--dev"]).dev is True
