"""Tests du point d'entrée et du pont Python ↔ interface (sans ouvrir de fenêtre)."""

import sys
from pathlib import Path

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
    assert sorted(public) == ["answer_question", "assemble_conductor", "check_transposition",
                              "choose_file", "choose_pack_file", "choose_save_path",
                              "edit_score", "export_pack", "export_score", "extract_parts",
                              "get_app_info",
                              "get_export_options", "get_instruments", "get_measure",
                              "get_page", "get_piece_scores", "get_progress",
                              "get_questions", "get_rendering",
                              "get_rules", "get_score_instrument", "import_pack",
                              "list_packs", "list_scores", "open_file", "ping", "remove_pack",
                              "set_rule_enabled",
                              "set_score_instrument", "transpose_score", "undo_answer",
                              "undo_edit"]


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


def test_parse_check_option():
    assert app.parse_args([]).check is None
    assert app.parse_args(["--check"]).check == ""
    assert app.parse_args(["--check", "partie.pdf"]).check == "partie.pdf"


def test_self_check(tmp_path, monkeypatch):
    """Diagnostic : outils trouvés (ici aucun), et lecture complète d'une partition."""
    import json

    from recomuse import selfcheck
    from recomuse.recognition import tools
    from recomuse.recognition.tools import ToolsStatus

    from synthetic import part_pdf

    monkeypatch.setattr(tools, "check_tools", lambda: ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[],
        missing_languages=list(tools.OCR_LANGUAGES)))
    report = selfcheck.run(part_pdf(tmp_path / "partie.pdf"))
    assert report["installed"] is False and report["audiveris"] == {"path": None,
                                                                    "bundled": False}
    assert report["ok"] is False                      # outils absents
    [part] = report["score"]["parts"]
    assert report["score"]["error"] is None and part["measures"] == 24 and part["exported"]
    saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert saved["score"]["file"] == "partie.pdf"
    broken = selfcheck.run(tmp_path / "absent.pdf")
    assert broken["score"]["error"].startswith("ScoreImportError")
