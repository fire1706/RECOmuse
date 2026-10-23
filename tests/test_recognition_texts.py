"""Tests de la lecture des textes : MusicXML d'Audiveris, TSV de Tesseract, analyse de l'en-tête."""

import zipfile
from pathlib import Path

import numpy as np
import pytest

from recomuse.importer.loading import write_png
from recomuse.recognition import ocr
from recomuse.recognition.header import (
    HeaderInfo,
    analyze_header,
    complete_with_credits,
    is_composer,
    is_instrument,
    is_noise,
    is_tempo,
    normalize,
)
from recomuse.recognition.musicxml import CreditText, summarize_movement
from recomuse.recognition.ocr import OcrLine

from synthetic import staff_page

# --- MusicXML ------------------------------------------------------------------------

SCORE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <identification><miscellaneous>
    <miscellaneous-field name="source-file">C:/partition.tif</miscellaneous-field>
    <miscellaneous-field name="source-sheet-1">12 13</miscellaneous-field>
    <miscellaneous-field name="source-sheet-2">1</miscellaneous-field>
  </miscellaneous></identification>
  <credit page="1"><credit-words default-x="586" default-y="1651" font-size="17">Serenata
    Égyptienne</credit-words></credit>
  <credit page="1"><credit-words default-x="10" default-y="10" font-size="8">  </credit-words></credit>
  <part-list><score-part id="P1"><part-name>Euphonium</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1"><attributes><time><beats>2</beats><beat-type>4</beat-type></time>
      </attributes><direction><direction-type><words>Tempo di marcia</words></direction-type>
      </direction></measure>
    <measure number="2"/>
    <measure number="3"><attributes><time><beats>3</beats><beat-type>4</beat-type></time>
      </attributes></measure>
  </part>
</score-partwise>"""


def write_mxl(path, xml, inner_name="partition.xml"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml",
                         f'<container><rootfiles><rootfile full-path="{inner_name}"/>'
                         f"</rootfiles></container>")
        archive.writestr(inner_name, xml)
    return path


def test_summarize_movement(tmp_path):
    summary = summarize_movement(write_mxl(tmp_path / "livre.mvt1.mxl", SCORE_XML))
    assert summary.sheet_systems == {1: [12, 13], 2: [1]}
    assert summary.part_names == ["Euphonium"]
    assert summary.measure_count == 3
    assert summary.time_signatures == ["2/4", "3/4"]
    assert summary.words == ["Tempo di marcia"]
    # Les retours à la ligne sont remplacés par des espaces ; les crédits vides sont ignorés.
    assert summary.credits == [CreditText("Serenata Égyptienne", 586.0, 1651.0, 17.0)]


def test_container_without_rootfile_is_refused(tmp_path):
    path = tmp_path / "x.mxl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", "<container/>")
    with pytest.raises(ValueError):
        summarize_movement(path)


# --- Tesseract -------------------------------------------------------------------------

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t2480\t400\t-1\t\n"            # niveau page : ignoré
    "5\t1\t1\t1\t1\t1\t100\t60\t80\t40\t92\tFlûte\n"
    "5\t1\t1\t1\t1\t2\t190\t62\t30\t38\t90\t1\n"
    "5\t1\t1\t1\t1\t3\t230\t60\t30\t40\t12\t~\n"            # confiance trop faible
    "5\t1\t2\t1\t1\t1\t800\t50\t300\t90\t95\tMARCHE\n"
    "5\t1\t3\t1\t1\t1\t900\t300\t20\t20\t-1\t \n"           # mot vide
)


def test_parse_tsv_groups_words_into_lines():
    lines = ocr.parse_tsv(TSV, offset_y=1000)
    assert [line.text for line in lines] == ["MARCHE", "Flûte 1"]  # triées de haut en bas
    flute = lines[1]
    assert (flute.left, flute.top, flute.width, flute.height) == (100, 1060, 120, 40)
    assert flute.confidence == 91.0


def test_header_bottom_is_above_first_staff():
    page = staff_page()  # première portée à 250 pixels du haut, interligne 22
    bottom = ocr.header_bottom(page, interline=22)
    assert 250 - 3.5 * 22 <= bottom <= 250 - 0.5 * 22


def test_header_bottom_cuts_in_the_white_gap_below_the_text():
    """Le tempo écrit juste au-dessus de la portée doit être gardé en entier."""
    page = staff_page()
    page[:250] = 255                                 # rien au-dessus de la première portée
    page[150:200, 100:400] = 0                       # un « texte » de 150 à 200
    page[215:250, 600:603] = 0                       # une hampe de note qui dépasse
    bottom = ocr.header_bottom(page, interline=22)
    assert 200 <= bottom < 215


def test_header_bottom_without_staff():
    blank = np.full((1000, 800), 255, np.uint8)
    assert ocr.header_bottom(blank, interline=None) == 250


def test_tesseract_command(tmp_path):
    (tmp_path / "fra.traineddata").write_bytes(b"")
    command = ocr.tesseract_command(Path("t.exe"), Path("h.png"), tmp_path)
    assert command[:3] == ["t.exe", "h.png", "stdout"]
    assert command[command.index("-l") + 1] == "fra"
    assert "tessedit_create_tsv=1" in command


def test_read_header(tmp_path, fake_tesseract):
    (tmp_path / "fra.traineddata").write_bytes(b"")
    page = tmp_path / "page-001.png"
    write_png(page, staff_page())
    lines = ocr.read_header(fake_tesseract, tmp_path, page, 22, tmp_path)
    assert "MARCHE D'ACOZ" in [line.text for line in lines]
    assert (tmp_path / "page-001-header.png").is_file()


def test_read_header_failure(tmp_path, fake_tesseract, monkeypatch):
    monkeypatch.setenv("FAKE_TESSERACT_MODE", "fail")
    (tmp_path / "fra.traineddata").write_bytes(b"")
    page = tmp_path / "page-001.png"
    write_png(page, staff_page())
    with pytest.raises(ocr.OcrError):
        ocr.read_header(fake_tesseract, tmp_path, page, 22, tmp_path)


def test_no_header_when_staff_touches_the_top(tmp_path, fake_tesseract):
    (tmp_path / "fra.traineddata").write_bytes(b"")
    page = tmp_path / "page-001.png"
    write_png(page, staff_page()[240:])  # première portée tout en haut
    assert ocr.read_header(fake_tesseract, tmp_path, page, 22, tmp_path) == []


# --- Analyse de l'en-tête ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Solo Bb Cornet.", "ALTO Sax 1", "Alto Saxophone 2", "Flûte I", "Klarinette in B",
    "1ste Bugel Bb", "Horn in F", "Cor 2 en Fa", "Bas Sib", "Tuba in Es", "Euphonium",
    "Trompete III in B", "(CONDUCTOR)", "Schlagzeug",
])
def test_instruments(text):
    assert is_instrument(text)


@pytest.mark.parametrize("text", [
    "Serenata Égyptienne", "BLUES ON THE HILL", "corps de ballet", "Music from The Incredibles",
    "Paul Lincke", "Basic Rock",
])
def test_not_instruments(text):
    assert not is_instrument(text)


@pytest.mark.parametrize("text", [
    "Allegretto Modto", "MODERATE SWING", "Vivace", "Tempo di marcia", "♩ = 120", "J=96",
    "Moderato", "Langsam", "Mod.",
])
def test_tempos(text):
    assert is_tempo(text)


@pytest.mark.parametrize("text", ["ZAPATEADO", "Marsupilami", "Pablo De Sarasate"])
def test_not_tempos(text):
    assert not is_tempo(text)


@pytest.mark.parametrize(("text", "expected"), [
    ("arr. Marco Marzi", True), ("Bearb.: Hans Müller", True), ("Music by John Williams", True),
    ("Music from The Incredibles", False), ("Paul Lincke", False),
])
def test_composers(text, expected):
    assert is_composer(text) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("A-€*", True), ("_ -", True), ("i", True), ("= 7", True), ("Clar", False), ("Trio", False),
])
def test_noise(text, expected):
    assert is_noise(text) == expected


def test_normalize():
    assert normalize("Flöte Égyptienne") == "flote egyptienne"


def line(text, left, top, height, width=None):
    return OcrLine(text=text, left=left, top=top, width=width or len(text) * height // 2,
                   height=height, confidence=90)


def test_analyze_typical_part_header():
    """En-tête comme celui de « Zapateado » : titre centré, instrument à gauche, auteurs à droite."""
    lines = [
        line("ZAPATEADO", 850, 60, 71),
        line("Alto Saxophone 2", 105, 150, 48),
        line("Pablo De Sarasate (1844 - 1908)", 1683, 160, 37),
        line("(arr. Marco Marzi)", 1926, 210, 35),
        line("A", 291, 330, 15),
        line("Vivace", 456, 330, 38),
    ]
    info = analyze_header(lines, page_width=2480)
    assert info == HeaderInfo(
        title="ZAPATEADO",
        instrument="Alto Saxophone 2",
        tempo="Vivace",
        composers=["Pablo De Sarasate (1844 - 1908)", "arr. Marco Marzi"],
        other=[],
    )


def test_title_is_the_biggest_centered_text():
    lines = [line("Edition Molenaar", 100, 40, 30), line("MARCHE D'ACOZ", 900, 80, 90),
             line("Trio", 300, 300, 30)]
    info = analyze_header(lines, page_width=2480)
    assert info.title == "MARCHE D'ACOZ"
    assert info.other == ["Edition Molenaar", "Trio"]


def test_first_instrument_wins():
    """« Solo Bb Cornet » au-dessus de « (CONDUCTOR) » : le premier est l'instrument."""
    lines = [line("Solo Bb Cornet.", 291, 30, 46), line("(CONDUCTOR .)", 285, 90, 60)]
    info = analyze_header(lines, page_width=2550)
    assert info.instrument == "Solo Bb Cornet"
    assert info.title == "CONDUCTOR"


def test_empty_header():
    assert analyze_header([], page_width=2480) == HeaderInfo()


def test_credits_fill_missing_fields():
    credits = [CreditText("PAUL LINCKE.", 1049, 1616, 14),
               CreditText("Serenata Égyptienne", 586, 1651, 17),
               CreditText("Flute 1", 100, 1650, 12),
               CreditText("_ -", 1, 1, 1)]
    info = complete_with_credits(HeaderInfo(), credits)
    assert info.title == "Serenata Égyptienne"
    assert info.instrument == "Flute 1"


def test_credits_do_not_replace_ocr():
    info = complete_with_credits(HeaderInfo(title="Amina", instrument="Cornet"),
                                 [CreditText("Autre titre", 0, 0, 30)])
    assert (info.title, info.instrument) == ("Amina", "Cornet")


def test_big_title_that_looks_like_a_tempo():
    """« Marche » est aussi un mot de tempo : la taille du texte doit l'emporter."""
    lines = [line("Bugle 1 Sib", 100, 150, 40), line("MARCHE D'ACOZ", 900, 60, 90),
             line("Allegro", 150, 300, 40)]
    info = analyze_header(lines, page_width=2480)
    assert info.title == "MARCHE D'ACOZ"
    assert info.tempo == "Allegro"
    assert info.instrument == "Bugle 1 Sib"
