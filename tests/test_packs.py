"""Tests des packs d'apprentissage (learning/packs.py) : un membre partage, un autre importe."""

import json
import zipfile

import pytest

from recomuse import library
from recomuse.api import Api
from recomuse.learning import packs, rules
from recomuse.learning.corrections import CorrectionService, NewSymbol
from recomuse.model.store import load_model, save_model
from recomuse.questions.session import QuestionSession
from recomuse.recognition import tools
from recomuse.recognition.tools import ToolsStatus
from recomuse.storage import database

from synthetic import part_pdf
from validation_helpers import four_four, measure, model_of, note, treble

KEY = "time_signature_missed:P1:m2,m3,m4,m5"


def three_four_model():
    measures = [measure("m1", [note(f"m1.n{k}", "C", 5, "1") for k in range(4)],
                        [treble(), four_four()])]
    measures += [measure(f"m{k}", [note(f"m{k}.n{j}", "C", 5, "1") for j in range(3)])
                 for k in range(2, 6)]
    return model_of(measures)


def new_score(conn, title="Marche") -> int:
    with conn:
        cursor = conn.execute("INSERT INTO scores (title, part_name, source_path) VALUES (?, ?, ?)",
                              (title, "Flûte", "fictif.pdf"))
    save_model(conn, cursor.lastrowid, three_four_model())
    return cursor.lastrowid


@pytest.fixture
def no_tools(monkeypatch):
    monkeypatch.setattr(tools, "check_tools", lambda: ToolsStatus(
        audiveris=None, tesseract=None, tessdata=None, languages=[], missing_languages=[]))


@pytest.fixture
def other_conn():
    """La base d'un autre membre de la fanfare."""
    connection = database.connect(":memory:")
    yield connection
    connection.close()


def test_export_contains_answers_and_corrected_parts_but_no_images(conn, tmp_path, no_tools):
    session = QuestionSession(conn, work_dir=tmp_path / "travail")
    for _ in range(2):
        session.answer(new_score(conn), KEY, "accept")
    [opened] = library.open_file(conn, part_pdf(tmp_path / "marche.pdf"),
                                 work_root=tmp_path / "travail")
    measure_id = load_model(conn, opened["score_id"]).parts[0].measures[1].id
    CorrectionService(conn).apply_group(opened["score_id"], [], source="manual",
                                        additions=[NewSymbol(measure_id, "multirest",
                                                             {"count": 3})])

    result = packs.export_pack(conn, tmp_path / "mon pack", author="  Claire ")
    assert result["path"].endswith("mon pack.recomuse-pack")
    assert (result["answers"], result["scores"]) == (2, 1)
    with zipfile.ZipFile(result["path"]) as archive:
        assert sorted(archive.namelist()) == ["answers.json", "manifest.json", "scores.json"]
        manifest = json.loads(archive.read("manifest.json"))
        [score] = json.loads(archive.read("scores.json"))
    assert manifest["author"] == "Claire" and manifest["format"] == packs.PACK_FORMAT
    assert score["title"] == "MARCHE D'ACOZ" and len(score["fingerprints"]) == 1
    assert score["corrections"][0]["new_value"] == {"count": 3}
    assert "image" not in json.dumps(score)                  # aucune image dans le pack
    alone = packs.export_pack(conn, tmp_path / "réponses.recomuse-pack", include_scores=False)
    assert alone["scores"] == 0


def test_another_member_imports_and_benefits(conn, other_conn, tmp_path, no_tools):
    """Claire répond et corrige ; Marc importe son pack : ses règles en profitent, et la
    même partie ouverte chez lui reprend les corrections de Claire."""
    session = QuestionSession(conn, work_dir=tmp_path / "travail")
    for _ in range(2):
        session.answer(new_score(conn), KEY, "accept")
    pdf = part_pdf(tmp_path / "marche.pdf")
    [opened] = library.open_file(conn, pdf, work_root=tmp_path / "claire")
    measure_id = load_model(conn, opened["score_id"]).parts[0].measures[1].id
    CorrectionService(conn).apply_group(opened["score_id"], [], source="manual",
                                        additions=[NewSymbol(measure_id, "multirest",
                                                             {"count": 3})])
    pack = packs.export_pack(conn, tmp_path / "claire", author="Claire")["path"]

    imported = packs.import_pack(other_conn, pack)
    assert (imported["author"], imported["answers"], imported["scores"]) == ("Claire", 2, 1)
    with pytest.raises(packs.PackError) as error:
        packs.import_pack(other_conn, pack)
    assert error.value.code == "pack_already_imported"

    # Une réponse de Marc, sur une 3e partition : la règle naît (2 partitions de Claire).
    marc = QuestionSession(other_conn, work_dir=tmp_path / "marc")
    marc.answer(new_score(other_conn), KEY, "accept")
    [rule] = rules.learned_rules(other_conn)
    assert (rule.evidence, rule.from_packs) == (3, 2)
    assert marc.state(new_score(other_conn))["answered_by_rules"] == 1

    # Marc ouvre le même PDF (copie à lui) : les corrections de Claire sont reprises.
    [mine] = library.open_file(other_conn, pdf, work_root=tmp_path / "marc")
    assert mine["memory"]["from_pack"] == imported["id"]
    assert mine["memory"]["author"] == "Claire" and mine["memory"]["applied"] == 1
    again = load_model(other_conn, mine["score_id"]).find_measure(measure_id)[1]
    assert [(s.kind, s.value) for s in again.attributes] == [("multirest", {"count": 3})]

    # Retirer le pack : ses réponses ne comptent plus (ce qui est corrigé le reste).
    packs.remove_pack(other_conn, imported["id"])
    assert packs.list_packs(other_conn) == [] and rules.learned_rules(other_conn) == []
    assert other_conn.execute("SELECT COUNT(*) FROM pack_scores").fetchone()[0] == 0


def test_bad_files_are_refused(conn, tmp_path):
    not_zip = tmp_path / "faux.recomuse-pack"
    not_zip.write_text("bonjour", encoding="utf-8")
    incomplete = tmp_path / "incomplet.recomuse-pack"
    with zipfile.ZipFile(incomplete, "w") as archive:
        archive.writestr("manifest.json", "{}")
    newer = tmp_path / "futur.recomuse-pack"
    with zipfile.ZipFile(newer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"uuid": "x", "format": 99}))
        archive.writestr("answers.json", "[]")
        archive.writestr("scores.json", "[]")
    broken = tmp_path / "abime.recomuse-pack"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"uuid": "y", "format": 1}))
        archive.writestr("answers.json", json.dumps([{"signature": {"code": "x"}}]))
        archive.writestr("scores.json", "[]")
    for path, code in [(not_zip, "not_a_pack"), (incomplete, "not_a_pack"),
                       (newer, "pack_too_new"), (broken, "not_a_pack"),
                       (tmp_path / "absent.recomuse-pack", "not_a_pack")]:
        with pytest.raises(packs.PackError) as error:
            packs.import_pack(conn, path)
        assert error.value.code == code
    assert packs.list_packs(conn) == []


def test_api_pack_methods(conn, tmp_path):
    api = Api(conn, ":memory:")
    assert api.choose_pack_file(True, "Pack", "x") is None          # pas de fenêtre
    written = api.export_pack(str(tmp_path / "vide"), "", True)
    assert (written["answers"], written["scores"]) == (0, 0)
    assert api.import_pack(str(tmp_path / "absent")) == {"error": "not_a_pack"}
    other = Api(database.connect(":memory:"), ":memory:")
    imported = other.import_pack(written["path"])
    assert imported["author"] is None
    assert [p["id"] for p in other.list_packs()] == [imported["id"]]
    assert other.remove_pack(imported["id"]) == {"packs": []}
