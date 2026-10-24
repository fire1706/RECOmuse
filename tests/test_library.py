"""Tests de l'ouverture d'un fichier (library.py) et des méthodes du pont qui s'en servent."""

import pytest

from recomuse import library
from recomuse.api import Api
from recomuse.model.store import load_model
from recomuse.progress import ReadingProgress
from recomuse.recognition import tools
from recomuse.recognition.tools import ToolsStatus

from synthetic import part_pdf


@pytest.fixture
def no_tools(monkeypatch):
    """Ni Audiveris ni Tesseract : une partie vectorielle se lit quand même."""
    monkeypatch.setattr(tools, "check_tools", lambda: ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[], missing_languages=[]))


def test_open_file_reads_and_stores_the_score(conn, tmp_path, no_tools):
    pdf = part_pdf(tmp_path / "Marche d'Acoz (flûte).pdf")
    progress = ReadingProgress()
    [summary] = library.open_file(conn, pdf, progress=progress,
                                  work_root=tmp_path / "travail")
    assert progress.to_dict()["stage"] == "done" and progress.to_dict()["fraction"] == 1.0
    assert summary["title"] == "MARCHE D'ACOZ" and summary["instrument"] == "Flute 1"
    assert summary["measure_count"] == 24 and summary["pages"] == [1]
    assert summary["source_name"] == pdf.name
    model = load_model(conn, summary["score_id"])
    assert sum(m.length for m in model.parts[0].measures) == 24
    # Dossier de travail sans caractères gênants ; le fichier d'origine n'est pas touché.
    assert (tmp_path / "travail" / "Marche_d_Acoz_flûte").is_dir()
    assert library.list_scores(conn) == [summary]


def test_api_open_file_and_questions(conn, tmp_path, no_tools, monkeypatch):
    monkeypatch.setattr("recomuse.paths.imports_dir", lambda: tmp_path / "travail")
    api = Api(conn, ":memory:")
    result = api.open_file(str(part_pdf(tmp_path / "partie.pdf")))
    [score] = result["scores"]
    assert api.get_progress() == {"stage": None}
    assert api.list_scores() == [score]
    state = api.get_questions(score["score_id"])
    assert state["score_id"] == score["score_id"] and "questions" in state


def test_api_errors_are_codes(conn, tmp_path):
    api = Api(conn, ":memory:")
    assert api.open_file(str(tmp_path / "absent.pdf")) == {"error": "file_not_found"}
    assert api.get_questions(999) == {"error": "question_failed"}
    assert api.answer_question(999, "k", "accept") == {"error": "question_failed"}
    assert api.undo_answer(999) == {"error": "question_failed"}
    # Pas de fenêtre (tests) : la fenêtre « Ouvrir » ne s'ouvre pas.
    assert api.choose_file("Partitions") is None


def test_only_one_reading_at_a_time(conn, tmp_path):
    api = Api(conn, ":memory:")
    api._busy.acquire()
    try:
        assert api.open_file(str(tmp_path / "x.pdf")) == {"error": "busy"}
    finally:
        api._busy.release()


def test_piece_of_groups_parts_by_title(conn):
    from recomuse.model.score import ScoreModel
    from recomuse.model.store import save_model

    def add(title, source):
        with conn:
            cursor = conn.execute("INSERT INTO scores (title, source_path) VALUES (?, ?)",
                                  (title, source))
        save_model(conn, cursor.lastrowid, ScoreModel(title=title))
        return cursor.lastrowid

    flute = add("Marche d'Acoz", "flute.pdf")
    trumpet = add("MARCHE D’ACOZ", "trompette.pdf")       # autre fichier, même morceau
    other = add("Zorba", "zorba.pdf")
    untitled_a = add(None, "groupe.pdf")
    untitled_b = add(None, "groupe.pdf")
    add(None, "autre.pdf")
    assert library.piece_of(conn, flute) == [flute, trumpet]
    assert library.piece_of(conn, other) == [other]
    assert library.piece_of(conn, untitled_b) == [untitled_a, untitled_b]
    assert library.piece_of(conn, 999) == []


def test_page_view_and_rendering(conn, tmp_path, no_tools, monkeypatch):
    monkeypatch.setattr("recomuse.paths.imports_dir", lambda: tmp_path / "travail")
    api = Api(conn, ":memory:")
    [score] = api.open_file(str(part_pdf(tmp_path / "partie.pdf")))["scores"]
    sid = score["score_id"]

    view = api.get_page(sid, 1)
    assert view["image"].startswith("data:image/jpeg;base64,")
    assert view["pages"] == [1] and view["width"] > 0 and view["height"] > 0
    assert len(view["measures"]) == 24
    first = view["measures"][0]
    assert first["number"] == 1 and len(first["bbox"]) == 4 and first["part_id"] == "P1"
    assert api.get_page(sid, 9) == {"error": "page_not_found"}

    rendering = api.get_rendering(sid)
    assert rendering["mei"].count("<measure ") == 24
    assert set(rendering["measures"].values()) == {m["id"] for m in view["measures"]}
    assert set(rendering["measure_pages"].values()) == {1}
    assert api.get_rendering(999) == {"error": "score_not_found"}


def test_simultaneous_calls_do_not_mix(conn, tmp_path, no_tools, monkeypatch):
    """L'interface envoie plusieurs demandes à la fois (comme pywebview, chacune dans son
    fil) : toutes doivent réussir, la connexion à la base étant partagée."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr("recomuse.paths.imports_dir", lambda: tmp_path / "travail")
    api = Api(conn, ":memory:")
    [score] = api.open_file(str(part_pdf(tmp_path / "partie.pdf")))["scores"]
    sid = score["score_id"]
    calls = [lambda: api.get_rendering(sid), lambda: api.get_page(sid, 1),
             lambda: api.get_questions(sid), lambda: api.list_scores(),
             lambda: api.get_app_info()] * 6
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda call: call(), calls))
    assert not [r for r in results if isinstance(r, dict) and "error" in r]


def test_cancelled_reading_stores_nothing(conn, tmp_path, no_tools):
    from recomuse.progress import ReadingCancelled

    progress = ReadingProgress()
    progress.cancel()
    with pytest.raises(ReadingCancelled):
        library.open_file(conn, part_pdf(tmp_path / "partie.pdf"), progress=progress,
                          work_root=tmp_path / "travail")
    assert library.list_scores(conn) == []


def test_api_progress_when_idle_and_cancel_without_reading(conn):
    api = Api(conn, ":memory:")
    assert api.get_progress() == {"stage": None}
    assert api.cancel_reading() == {"cancelling": False}


def test_closing_the_window_stops_the_reading(conn, tmp_path, no_tools, monkeypatch):
    import threading
    import time

    from recomuse.progress import ReadingCancelled

    monkeypatch.setattr("recomuse.paths.imports_dir", lambda: tmp_path / "travail")

    def slow_import(source, work_dir, on_progress=None):
        # Import qui dure, mais s'arrête dès que l'annulation est demandée.
        for page in range(100):
            on_progress(page, 100)
            time.sleep(0.05)
        raise AssertionError("pas annulé")
    monkeypatch.setattr(library, "import_score", slow_import)
    api = Api(conn, ":memory:")
    result = {}
    reader = threading.Thread(target=lambda: result.update(api.open_file("partie.pdf")))
    reader.start()
    while api.get_progress()["stage"] is None:
        time.sleep(0.01)
    assert api._stop_reading(timeout=5)
    reader.join()
    assert result == {"error": ReadingCancelled.code}
