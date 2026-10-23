"""Tests de l'appel d'Audiveris, avec un faux Audiveris (tests/fakes/fake_audiveris.py)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from recomuse.importer import ImportedPage
from recomuse.importer.loading import write_png
from recomuse.recognition import audiveris
from recomuse.recognition.audiveris import AudiverisError, BookImage

from synthetic import staff_page


def make_pages(tmp_path, specs):
    """specs : liste de (numéro de page, a des portées ?). None = page blanche."""
    pages = []
    for number, has_staff in specs:
        page = ImportedPage(page_number=number, kind="scanned", image_path=None)
        if has_staff is not None:
            page.image_path = tmp_path / f"page-{number:03d}.png"
            write_png(page.image_path, staff_page(dpi=100))
            page.interline = 22 if has_staff else None
        pages.append(page)
    return pages


def make_book(tmp_path, sheets=2):
    pages = make_pages(tmp_path, [(n, True) for n in range(1, sheets + 1)])
    return audiveris.build_book_image(pages, tmp_path / "work" / "livre.tif")


# --- Construction du livre -------------------------------------------------------------

def test_book_keeps_only_pages_with_staves(tmp_path):
    pages = make_pages(tmp_path, [(1, False), (2, True), (3, None), (4, True)])
    book = audiveris.build_book_image(pages, tmp_path / "livre.tif")

    assert book.sheet_pages == [2, 4]
    ok, images = cv2.imdecodemulti(np.fromfile(book.path, np.uint8), cv2.IMREAD_UNCHANGED)
    assert ok and len(images) == 2
    assert images[0].shape == staff_page(dpi=100).shape


def test_small_staves_are_enlarged(tmp_path):
    pages = make_pages(tmp_path, [(1, True), (2, True)])
    pages[1].interline = 10  # conducteur : portées minuscules
    book = audiveris.build_book_image(pages, tmp_path / "livre.tif")

    assert book.sheet_scales == [1.0, 2.0]
    ok, images = cv2.imdecodemulti(np.fromfile(book.path, np.uint8), cv2.IMREAD_UNCHANGED)
    assert ok
    assert images[1].shape[0] == 2 * images[0].shape[0]


@pytest.mark.parametrize(("interline", "scale"), [(22, 1.0), (15, 1.0), (14, 1.429),
                                                  (13, 1.538)])
def test_sheet_scale_small_page(interline, scale):
    """Petite image : seul l'interligne visé (20 pixels) limite l'agrandissement."""
    assert audiveris.sheet_scale(interline, 1000, 1400) == scale


def test_sheet_scale_respects_audiveris_size_limit():
    """Page A4 à 300 dpi : Audiveris refuse plus de 20 millions de pixels."""
    scale = audiveris.sheet_scale(9, 2480, 3508)
    assert scale == pytest.approx(1.5, abs=0.01)
    assert 2480 * 3508 * scale**2 <= 20_000_000


def test_book_without_music_is_refused(tmp_path):
    pages = make_pages(tmp_path, [(1, False), (2, None)])
    with pytest.raises(AudiverisError) as info:
        audiveris.build_book_image(pages, tmp_path / "livre.tif")
    assert info.value.code == "no_music_recognized"


# --- Ligne de commande et journal ------------------------------------------------------

def test_command_line(tmp_path):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "fra.traineddata").write_bytes(b"")
    (tessdata / "nld.traineddata").write_bytes(b"")

    command = audiveris.audiveris_command(Path("A.exe"), Path("livre.tif"), Path("out"), tessdata)
    assert command[:3] == ["A.exe", "-batch", "-export"]
    assert command[-2:] == ["--", "livre.tif"]
    assert "org.audiveris.omr.text.Language.defaultSpecification=fra+nld" in command


def test_command_line_without_tessdata():
    command = audiveris.audiveris_command(Path("A.exe"), Path("l.tif"), Path("out"), None)
    assert "-constant" not in command


def test_parse_progress_line():
    line = "INFO  [livre#3]          StepMonitoring 98   | HEADS"
    assert audiveris.parse_progress_line(line) == (3, "HEADS")
    assert audiveris.parse_progress_line("INFO  [livre#1]  ScaleStep 65 | Scale{...}") is None
    assert audiveris.parse_progress_line("INFO  [livre#1] StepMonitoring 98 | UNKNOWN") is None


def test_steps_done():
    assert audiveris.steps_done(1, "LOAD") == 0
    assert audiveris.steps_done(2, "LOAD") == len(audiveris.AUDIVERIS_STEPS)
    assert audiveris.steps_done(1, "PAGE") == len(audiveris.AUDIVERIS_STEPS) - 1


def test_movement_files_are_in_numeric_order(tmp_path):
    for n in (10, 2, 1):
        (tmp_path / f"livre.mvt{n}.mxl").write_bytes(b"")
    (tmp_path / "autre.mvt3.mxl").write_bytes(b"")
    names = [p.name for p in audiveris.movement_files(tmp_path)]
    assert names == ["livre.mvt1.mxl", "livre.mvt2.mxl", "livre.mvt10.mxl"]


def test_single_movement_file(tmp_path):
    (tmp_path / "livre.mxl").write_bytes(b"")
    assert [p.name for p in audiveris.movement_files(tmp_path)] == ["livre.mxl"]


# --- Passage complet (faux Audiveris) --------------------------------------------------

def test_run(tmp_path, fake_audiveris):
    book = make_book(tmp_path)
    progress = []
    run = audiveris.run_audiveris(fake_audiveris, book, tmp_path / "out",
                                  on_progress=lambda d, t: progress.append((d, t)))

    assert [p.name for p in run.movement_paths] == ["livre.mvt1.mxl", "livre.mvt2.mxl"]
    assert run.omr_path.name == "livre.omr"
    assert run.log_path.name.startswith("livre-")
    total = 2 * len(audiveris.AUDIVERIS_STEPS)
    assert progress[0] == (0, total)
    assert progress[-1] == (total, total)
    assert [d for d, _ in progress] == sorted(d for d, _ in progress)
    assert any("StepMonitoring" in line for line in run.console_lines)


def test_old_results_are_removed(tmp_path, fake_audiveris):
    out = tmp_path / "out"
    out.mkdir()
    (out / "livre.mvt7.mxl").write_bytes(b"ancien")
    run = audiveris.run_audiveris(fake_audiveris, make_book(tmp_path), out)
    assert [p.name for p in run.movement_paths] == ["livre.mvt1.mxl", "livre.mvt2.mxl"]


@pytest.mark.parametrize(("mode", "code"), [("fail", "audiveris_failed"),
                                            ("empty", "no_music_recognized")])
def test_errors(tmp_path, fake_audiveris, monkeypatch, mode, code):
    monkeypatch.setenv("FAKE_AUDIVERIS_MODE", mode)
    with pytest.raises(AudiverisError) as info:
        audiveris.run_audiveris(fake_audiveris, make_book(tmp_path), tmp_path / "out")
    assert info.value.code == code
    assert info.value.log_path is not None  # le journal reste consultable


def test_timeout(tmp_path, fake_audiveris, monkeypatch):
    monkeypatch.setenv("FAKE_AUDIVERIS_MODE", "hang")
    with pytest.raises(AudiverisError) as info:
        audiveris.run_audiveris(fake_audiveris, make_book(tmp_path), tmp_path / "out",
                                timeout_seconds=2)
    assert info.value.code == "audiveris_timeout"


def test_tessdata_is_passed_to_audiveris(tmp_path, fake_audiveris):
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "fra.traineddata").write_bytes(b"")
    book = BookImage(path=make_book(tmp_path).path, sheet_pages=[1, 2])
    audiveris.run_audiveris(fake_audiveris, book, tmp_path / "out", tessdata=tessdata)
    args = (tmp_path / "out" / "fake-args.txt").read_text(encoding="utf-8").splitlines()
    assert "org.audiveris.omr.text.Language.defaultSpecification=fra" in args
