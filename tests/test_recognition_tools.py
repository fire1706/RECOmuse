"""Tests de la recherche des programmes externes."""

import pytest

from recomuse.recognition import tools


@pytest.fixture
def tessdata(tmp_path):
    folder = tmp_path / "tessdata"
    folder.mkdir()
    for lang in ("eng", "fra"):
        (folder / f"{lang}.traineddata").write_bytes(b"")
    return folder


def fake_program(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"")
    return path


def test_environment_variables_win(tmp_path, tessdata, monkeypatch):
    audiveris = fake_program(tmp_path, "MonAudiveris.exe")
    tesseract = fake_program(tmp_path, "MonTesseract.exe")
    monkeypatch.setenv("RECOMUSE_AUDIVERIS", str(audiveris))
    monkeypatch.setenv("RECOMUSE_TESSERACT", str(tesseract))
    monkeypatch.setenv("RECOMUSE_TESSDATA", str(tessdata))

    status = tools.check_tools()
    assert status.audiveris == audiveris
    assert status.tesseract == tesseract
    assert status.tessdata == tessdata
    assert status.languages == ["eng", "fra"]
    assert status.missing_languages == ["nld", "deu"]
    assert not status.ready


def test_ready_when_everything_is_there(tmp_path, tessdata, monkeypatch):
    for lang in ("nld", "deu"):
        (tessdata / f"{lang}.traineddata").write_bytes(b"")
    monkeypatch.setenv("RECOMUSE_AUDIVERIS", str(fake_program(tmp_path, "a.exe")))
    monkeypatch.setenv("RECOMUSE_TESSERACT", str(fake_program(tmp_path, "t.exe")))
    monkeypatch.setenv("RECOMUSE_TESSDATA", str(tessdata))

    status = tools.check_tools()
    assert status.ready
    assert status.to_dict()["ready"] is True


def test_missing_environment_target_is_ignored(tmp_path, monkeypatch):
    """Une variable qui pointe vers un fichier absent ne doit pas être retenue."""
    monkeypatch.setenv("RECOMUSE_AUDIVERIS", str(tmp_path / "absent.exe"))
    assert tools.find_audiveris() != tmp_path / "absent.exe"


def test_tessdata_in_local_data_dir(isolated_data_dir, monkeypatch):
    monkeypatch.delenv("RECOMUSE_TESSDATA", raising=False)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    folder = isolated_data_dir / tools.TESSDATA_DIRNAME
    folder.mkdir(parents=True)
    (folder / "nld.traineddata").write_bytes(b"")
    assert tools.find_tessdata() == folder


def test_empty_tessdata_folder_is_ignored(tmp_path, monkeypatch):
    empty = tmp_path / "vide"
    empty.mkdir()
    monkeypatch.setenv("RECOMUSE_TESSDATA", str(empty))
    assert tools.find_tessdata() != empty


def test_language_spec_keeps_preferred_order(tessdata):
    (tessdata / "deu.traineddata").write_bytes(b"")
    (tessdata / "osd.traineddata").write_bytes(b"")  # présent mais inutile ici
    assert tools.ocr_language_spec(tessdata) == "fra+eng+deu"


def test_require():
    with pytest.raises(tools.ToolNotFoundError) as info:
        tools.require(None, "audiveris_not_found")
    assert info.value.code == "audiveris_not_found"
