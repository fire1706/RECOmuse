"""Tests de l'import complet d'un fichier (PDF ou image)."""

import hashlib
import json

import cv2
import numpy as np
import pymupdf
import pytest

from recomuse.importer import ScoreImportError, import_score, register_score
from recomuse.importer.__main__ import main as cli_main
from recomuse.importer.loading import read_gray, read_image_file

from synthetic import (
    png_bytes,
    rotate,
    scanned_pdf,
    staff_page,
    vector_pdf,
    write_png_with_dpi,
)

# Taille d'une page A4 dessinée à 300 dpi.
A4_AT_300 = (2480, 3509)  # (largeur, hauteur) : 595 × 842 points × 300/72, arrondis par PyMuPDF


def read_png(path):
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- PDF -----------------------------------------------------------------------------

def test_vector_pdf(tmp_path):
    score = import_score(vector_pdf(tmp_path / "v.pdf", page_count=2), tmp_path / "out")

    assert score.source_kind == "vector_pdf"
    assert score.page_count == 2
    for number, page in enumerate(score.pages, start=1):
        assert page.page_number == number
        assert page.kind == "vector"
        assert page.rotation_degrees == 0
        assert page.image_path == tmp_path / "out" / f"page-{number:03d}.png"
        assert (page.width, page.height) == pytest.approx(A4_AT_300, abs=1)
        assert read_png(page.image_path).shape == (page.height, page.width)
        assert page.interline == pytest.approx(22, abs=1)
        # Pas de police de musique dans ce PDF de test : c'est signalé.
        assert page.warnings == ["no_music_font"]


def test_scanned_pdf_is_upscaled_and_straightened(tmp_path):
    crooked = rotate(staff_page(dpi=150), 1.5)
    score = import_score(scanned_pdf(tmp_path / "s.pdf", [crooked]), tmp_path / "out")

    page = score.pages[0]
    assert score.source_kind == "scanned_pdf"
    assert page.kind == "scanned"
    assert page.source_dpi == pytest.approx(150, abs=2)
    assert page.rotation_degrees == pytest.approx(-1.5, abs=0.1)
    assert (page.width, page.height) == pytest.approx(A4_AT_300, abs=1)
    # Interligne de 11 px à 150 dpi → 22 px à 300 dpi.
    assert page.interline == pytest.approx(22, abs=1)
    assert page.warnings == ["low_resolution"]


def test_large_skew_is_reported(tmp_path):
    crooked = rotate(staff_page(dpi=300), 4.0)
    page = import_score(scanned_pdf(tmp_path / "s.pdf", [crooked]), tmp_path / "out").pages[0]
    assert page.rotation_degrees == pytest.approx(-4.0, abs=0.1)
    assert "large_skew" in page.warnings


def test_blank_pages_are_kept_but_not_rendered(tmp_path):
    path = scanned_pdf(tmp_path / "s.pdf", [staff_page(), None, staff_page()])
    score = import_score(path, tmp_path / "out")

    assert [p.kind for p in score.pages] == ["scanned", "blank", "scanned"]
    assert score.pages[1].image_path is None
    assert sorted(f.name for f in (tmp_path / "out").iterdir()) == ["page-001.png",
                                                                    "page-003.png"]


def test_scanned_page_without_staff_is_reported(tmp_path):
    cover = np.full((1000, 700), 255, np.uint8)
    cv2.putText(cover, "MARCHE", (100, 500), cv2.FONT_HERSHEY_SIMPLEX, 4, 0, 10)
    page = import_score(scanned_pdf(tmp_path / "c.pdf", [cover]), tmp_path / "out").pages[0]
    assert page.interline is None
    assert "no_staff_found" in page.warnings


def test_progress_is_reported(tmp_path):
    calls = []
    import_score(vector_pdf(tmp_path / "v.pdf", page_count=3), tmp_path / "out",
                 on_progress=lambda done, total: calls.append((done, total)))
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_source_file_is_never_modified(tmp_path):
    source = scanned_pdf(tmp_path / "s.pdf", [rotate(staff_page(dpi=150), 2)])
    before = file_hash(source)
    import_score(source, tmp_path / "out")
    assert file_hash(source) == before


def test_paths_with_accents(tmp_path):
    folder = tmp_path / "Partitions de l'été"
    folder.mkdir()
    source = vector_pdf(folder / "Flûte 1ère.pdf")
    score = import_score(source, folder / "préparé")
    assert score.pages[0].image_path.is_file()


# --- Images --------------------------------------------------------------------------

def test_png_with_resolution(tmp_path):
    source = write_png_with_dpi(tmp_path / "p.png", staff_page(dpi=200), dpi=200)
    page = import_score(source, tmp_path / "out").pages[0]

    assert page.source_dpi == 200
    assert page.warnings == []
    assert page.interline == pytest.approx(22, abs=1)
    assert page.width == pytest.approx(2481, abs=3)


def test_png_without_resolution_is_estimated_from_staves(tmp_path):
    source = write_png_with_dpi(tmp_path / "p.png", staff_page(dpi=150), dpi=None)
    page = import_score(source, tmp_path / "out").pages[0]

    # Résolution devinée basse : signalée.
    assert page.warnings == ["dpi_estimated", "low_resolution"]
    assert page.source_dpi == pytest.approx(150, abs=15)
    assert page.interline == pytest.approx(22, abs=1)


def test_very_low_resolution_is_cleaned_in_black_and_white(tmp_path):
    # Capture d'écran ou scan à 90 dpi : la page agrandie passe en noir et blanc pur.
    source = write_png_with_dpi(tmp_path / "p.png", staff_page(dpi=90), dpi=None)
    page = import_score(source, tmp_path / "out").pages[0]
    assert page.warnings == ["dpi_estimated", "low_resolution"]
    assert page.source_dpi < 120
    assert set(np.unique(read_gray(page.image_path))) <= {0, 255}


def test_good_resolution_keeps_its_grey_levels(tmp_path):
    # Une page déjà à bonne résolution n'est pas passée en noir et blanc (Audiveris fait
    # lui-même mieux à partir des gris).
    pixels = cv2.GaussianBlur(staff_page(dpi=300), (5, 5), 0)
    source = write_png_with_dpi(tmp_path / "p.png", pixels, dpi=300)
    page = import_score(source, tmp_path / "out").pages[0]
    assert page.warnings == []
    assert len(np.unique(read_gray(page.image_path))) > 2


def test_meaningless_72_dpi_is_ignored(tmp_path):
    source = write_png_with_dpi(tmp_path / "p.png", staff_page(dpi=300), dpi=72)
    page = import_score(source, tmp_path / "out").pages[0]
    assert page.warnings == ["dpi_estimated"]
    assert page.source_dpi == pytest.approx(300, abs=15)


def test_crooked_jpeg(tmp_path):
    source = tmp_path / "photo.jpg"
    ok, data = cv2.imencode(".jpg", rotate(staff_page(), -2.0))
    assert ok
    data.tofile(source)
    page = import_score(source, tmp_path / "out").pages[0]
    assert page.rotation_degrees == pytest.approx(2.0, abs=0.1)


def test_transparent_png_gets_white_background(tmp_path):
    rgba = np.zeros((50, 60, 4), np.uint8)  # entièrement transparent (et « noir » dessous)
    rgba[20:30, :, 3] = 255                 # une bande opaque noire
    source = tmp_path / "t.png"
    source.write_bytes(png_bytes(rgba))

    pixels = read_image_file(source)[0].pixels
    assert pixels[0, 0] == 255
    assert pixels[25, 10] == 0


def test_multipage_tiff(tmp_path):
    source = tmp_path / "scan.tif"
    ok, data = cv2.imencodemulti(".tiff", [staff_page(), staff_page()])
    assert ok
    np.asarray(data).tofile(source)

    score = import_score(source, tmp_path / "out")
    assert score.source_kind == "image"
    assert [p.page_number for p in score.pages] == [1, 2]


# --- Erreurs -------------------------------------------------------------------------

def assert_import_error(path, code, tmp_path):
    with pytest.raises(ScoreImportError) as info:
        import_score(path, tmp_path / "out")
    assert info.value.code == code


def test_missing_file(tmp_path):
    assert_import_error(tmp_path / "absent.pdf", "file_not_found", tmp_path)


def test_unsupported_format(tmp_path):
    path = tmp_path / "lettre.docx"
    path.write_bytes(b"pas une partition")
    assert_import_error(path, "unsupported_format", tmp_path)


def test_damaged_pdf(tmp_path):
    path = tmp_path / "abime.pdf"
    path.write_bytes(b"ceci n'est pas un PDF")
    assert_import_error(path, "unreadable_file", tmp_path)


def test_damaged_image(tmp_path):
    path = tmp_path / "abime.png"
    path.write_bytes(b"ceci n'est pas une image")
    assert_import_error(path, "unreadable_file", tmp_path)


def test_encrypted_pdf(tmp_path):
    path = tmp_path / "protege.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw="secret", owner_pw="secret")
    doc.close()
    assert_import_error(path, "encrypted_pdf", tmp_path)


def test_only_blank_pages(tmp_path):
    assert_import_error(scanned_pdf(tmp_path / "b.pdf", [None, None]), "empty_document",
                        tmp_path)


# --- Base de données, export, ligne de commande ---------------------------------------

def test_register_score(conn, tmp_path):
    score = import_score(vector_pdf(tmp_path / "v.pdf", page_count=2), tmp_path / "out")
    score_id = register_score(conn, score, title="Marche de test", part_name="Flûte")

    row = conn.execute("SELECT * FROM scores WHERE id = ?", (score_id,)).fetchone()
    assert row["source_kind"] == "vector_pdf"
    assert row["page_count"] == 2
    assert row["title"] == "Marche de test"
    assert row["source_path"] == str(tmp_path / "v.pdf")


def test_to_dict_is_json_ready(tmp_path):
    score = import_score(scanned_pdf(tmp_path / "s.pdf", [staff_page(), None]), tmp_path / "out")
    data = json.loads(json.dumps(score.to_dict()))
    assert data["source_kind"] == "scanned_pdf"
    assert data["pages"][0]["image_path"].endswith("page-001.png")
    assert data["pages"][1]["image_path"] is None


def test_command_line(tmp_path, capsys):
    good = vector_pdf(tmp_path / "v.pdf")
    bad = tmp_path / "absent.pdf"
    assert cli_main([str(good), "--out", str(tmp_path / "out")]) == 0
    assert "vector_pdf" in capsys.readouterr().out
    assert cli_main([str(bad), "--out", str(tmp_path / "out")]) == 1
    assert "file_not_found" in capsys.readouterr().out


def test_small_staves_are_reported(tmp_path):
    """Conducteur aux portées minuscules : interligne de 8 pixels à 300 dpi."""
    tiny = staff_page(interline_at_300=8, thickness_at_300=1, systems=20)
    page = import_score(scanned_pdf(tmp_path / "c.pdf", [tiny]), tmp_path / "out").pages[0]
    assert page.interline == pytest.approx(8, abs=1)
    assert "small_staff" in page.warnings
