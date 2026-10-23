"""Tests de la construction du modèle : depuis la lecture vectorielle, depuis Audiveris
(MusicXML et projet .omr fabriqués), et assemblage des deux."""

import zipfile
from pathlib import Path

import pytest

from recomuse.importer import ImportedPage, ImportedScore
from recomuse.model import from_audiveris, from_vector
from recomuse.model.build import build_model
from recomuse.recognition.audiveris import AudiverisRun, BookImage
from recomuse.recognition.header import HeaderInfo
from recomuse.recognition.musicxml import MovementSummary
from recomuse.recognition.pipeline import RecognitionResult
from recomuse.vector.reader import interpret_page
from recomuse.vector.score import VectorScore

from vector_builder import HALF, SHARP, TREBLE, TREBLE_SHARPS, WHOLE, PageBuilder

# --- Lecture vectorielle ----------------------------------------------------------------------


def vector_score(pages: list[PageBuilder]) -> VectorScore:
    states = {}
    return VectorScore(source_path=None,
                       pages=[interpret_page(p.build(), n, states) for n, p in enumerate(pages, 1)])


def part_page(key=True, second_line=False):
    page = PageBuilder()
    page.staff(100, barlines=[300, 550])
    page.glyph(0, TREBLE, 55, 2)
    if key:
        page.key(0, 70, TREBLE_SHARPS[:1], SHARP)
    page.time(0, 80, "4", "4")
    page.note(0, 120, 1, code=WHOLE)                       # fa♯4 ronde
    page.note(0, 320, 4, code=HALF)
    page.note(0, 420, 4, code=HALF)
    if second_line:
        page.staff(200, barlines=[300, 550])
        page.glyph(1, TREBLE, 55, 2)
        page.key(1, 70, TREBLE_SHARPS[:1], SHARP)          # rappel : pas un changement
        page.note(1, 120, 4, code=WHOLE)
        page.note(1, 320, 4)                               # mesure trop courte
    return page


def test_vector_part_values_and_positions():
    measures = from_vector.build_part_measures(vector_score([part_page()]), rank=0)
    first = measures[0]
    assert [s.kind for s in first.attributes] == ["clef", "key", "time"]
    assert first.attributes[0].value == {"sign": "G", "line": 2}
    assert first.attributes[1].value == {"fifths": 1}
    assert first.attributes[2].value == {"beats": 4, "beat_type": 4}
    note = first.events[0]
    assert note.value["step"] == "F" and note.value["alter"] == 1
    assert note.value["duration"] == "4"
    assert note.confidence == 1.0 and note.source == "vector"
    # Points PDF → pixels à 300 dpi : x = 120 pt → 500 px.
    assert note.bbox[0] == pytest.approx(500)
    assert first.expected_duration == "4"


def test_repeated_key_at_line_start_is_not_a_symbol():
    measures = from_vector.build_part_measures(vector_score([part_page(second_line=True)]), 0)
    third = measures[2]
    assert [s.kind for s in third.attributes] == []


def test_wrong_measure_is_doubtful_but_pickup_is_not():
    measures = from_vector.build_part_measures(vector_score([part_page(second_line=True)]), 0)
    assert measures[3].events[0].confidence == from_vector.DOUBTFUL_CONFIDENCE

    pickup = PageBuilder()
    pickup.staff(100, barlines=[300, 550])
    pickup.glyph(0, TREBLE, 55, 2)
    pickup.time(0, 80, "4", "4")
    pickup.note(0, 120, 4)                                  # levée d'un temps
    pickup.note(0, 320, 4, code=WHOLE)
    measures = from_vector.build_part_measures(vector_score([pickup]), 0)
    assert measures[0].events[0].confidence == 1.0


def test_clef_values():
    assert from_vector.clef_value("bass", 6) == {"sign": "F", "line": 4}
    assert from_vector.clef_value("c", 4) == {"sign": "C", "line": 3}
    assert from_vector.clef_value("treble_8vb", 2) == {"sign": "G", "line": 2, "octave_change": -1}


# --- Audiveris : MusicXML + .omr fabriqués --------------------------------------------------------

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <defaults><page-layout><page-width>1300</page-width></page-layout></defaults>
  <part-list><score-part id="P1"><part-name>Flute</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>-1</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note default-x="50"><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration>
        <voice>1</voice><type>quarter</type></note>
      <note default-x="50"><chord/><pitch><step>C</step><octave>5</octave></pitch><duration>2</duration>
        <voice>1</voice><type>quarter</type></note>
      <note default-x="150"><pitch><step>G</step><octave>4</octave></pitch><duration>2</duration>
        <voice>1</voice><type>quarter</type><tie type="start"/></note>
      <note default-x="225"><rest/><duration>4</duration><voice>1</voice><type>half</type></note>
    </measure>
    <measure number="2">
      <note default-x="50"><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch>
        <duration>3</duration><voice>1</voice><type>quarter</type><dot/>
        <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>
      </note>
      <note default-x="900"><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration>
        <voice>1</voice><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""

SHEET = """<?xml version="1.0"?>
<sheet>
  <picture width="2600" height="3600"/>
  <page id="1"><system id="1">
    <stack id="1" left="200" right="800"/>
    <stack id="2" left="800" right="1400"/>
    <part id="1">
      <measure id="1"><head-chords>10 20</head-chords><rest-chords>30</rest-chords>
        <clefs>40</clefs><times>41</times></measure>
      <measure id="2"><head-chords>50</head-chords></measure>
    </part>
    <sig>
      <inters>
        <head-chord id="10" grade="0.9" staff="1"><bounds x="300" y="100" w="30" h="120"/></head-chord>
        <head id="11" grade="0.8" ctx-grade="0.85" staff="1" pitch="3"><bounds x="300" y="200" w="26" h="20"/></head>
        <head id="12" grade="0.6" staff="1" pitch="-2"><bounds x="300" y="150" w="26" h="20"/></head>
        <head-chord id="20" grade="0.9" staff="1"><bounds x="500" y="120" w="30" h="100"/></head-chord>
        <head id="21" grade="0.95" staff="1" pitch="1"><bounds x="500" y="180" w="26" h="20"/></head>
        <rest-chord id="30" grade="0.7" staff="1"><bounds x="650" y="150" w="20" h="40"/></rest-chord>
        <clef id="40" grade="0.99" staff="1"><bounds x="210" y="120" w="40" h="110"/></clef>
        <time-pair id="41" grade="0.97" staff="1"><bounds x="260" y="140" w="20" h="80"/></time-pair>
        <head-chord id="50" grade="0.88" staff="1"><bounds x="900" y="130" w="30" h="90"/></head-chord>
        <head id="51" grade="0.33" staff="1" pitch="0"><bounds x="900" y="170" w="26" h="20"/></head>
      </inters>
      <relations>
        <relation source="10" target="11"><containment/></relation>
        <relation source="10" target="12"><containment/></relation>
        <relation source="20" target="21"><containment/></relation>
        <relation source="50" target="51"><containment/></relation>
      </relations>
    </sig>
  </system></page>
</sheet>"""


def make_recognition(tmp_path: Path, page: int = 3, scale: float = 2.0) -> RecognitionResult:
    mxl = tmp_path / "livre.mxl"
    with zipfile.ZipFile(mxl, "w") as archive:
        archive.writestr("META-INF/container.xml",
                         '<container><rootfiles><rootfile full-path="livre.xml"/></rootfiles></container>')
        archive.writestr("livre.xml", MUSICXML)
    omr = tmp_path / "livre.omr"
    with zipfile.ZipFile(omr, "w") as archive:
        archive.writestr("book.xml", "<book/>")
        archive.writestr("sheet#1/sheet#1.xml", SHEET)
    book = BookImage(path=tmp_path / "livre.tif", sheet_pages=[page], sheet_scales=[scale])
    run = AudiverisRun(book=book, output_dir=tmp_path, omr_path=omr, movement_paths=[mxl],
                       log_path=None, duration_seconds=1.0)
    movement = MovementSummary(path=mxl, sheet_systems={1: [1]}, part_names=["Flute"],
                               measure_count=2, time_signatures=["4/4"])
    return RecognitionResult(run=run, movements=[movement],
                             header=HeaderInfo(title="ZAPATEADO", instrument="Flûte"))


def test_audiveris_values(tmp_path):
    first, second = from_audiveris.build_parts(make_recognition(tmp_path))[0]
    assert [s.kind for s in first.attributes] == ["clef", "key", "time"]
    assert first.attributes[1].value == {"fifths": -1}
    names = [(s.kind, s.value.get("step"), s.value["duration"], s.value.get("chord"))
             for s in first.events]
    assert names == [("note", "E", "1", False), ("note", "C", "1", True),
                     ("note", "G", "1", False), ("rest", None, "2", None)]
    assert first.events[2].value["tie_start"]
    tuplet_note = second.events[0]
    assert tuplet_note.value["alter"] == -1
    assert tuplet_note.value["dots"] == 1 and tuplet_note.value["tuplet"] == [3, 2]
    assert tuplet_note.value["duration"] == "3/2"
    assert first.expected_duration == "4"
    assert first.page == 3


def test_audiveris_positions_and_confidence(tmp_path):
    first, second = from_audiveris.build_parts(make_recognition(tmp_path, scale=2.0))[0]
    low, high, single, rest = first.events
    # Accord : la note grave (mi4) va avec la tête du bas (y = 200), la haute avec y = 150.
    # Coordonnées divisées par l'agrandissement de la feuille (2).
    assert low.bbox == (150.0, 100.0, 13.0, 10.0) and low.confidence == 0.85
    assert high.bbox == (150.0, 75.0, 13.0, 10.0) and high.confidence == 0.6
    assert single.confidence == 0.95
    assert rest.bbox == (325.0, 75.0, 10.0, 20.0) and rest.confidence == 0.7
    assert first.attributes[0].confidence == 0.99          # clé
    assert first.attributes[2].confidence == 0.97          # chiffrage
    # Armure absente du .omr : confiance par défaut.
    assert first.attributes[1].confidence == from_audiveris.UNKNOWN_CONFIDENCE
    # 2e mesure : la 1re note trouve sa tête ; la 2e n'a pas de correspondant.
    assert second.events[0].confidence == 0.33
    assert second.events[1].confidence == from_audiveris.UNKNOWN_CONFIDENCE
    assert second.events[1].bbox == second.bbox


def test_audiveris_without_omr(tmp_path):
    recognition = make_recognition(tmp_path)
    recognition.run.omr_path = None
    first, _ = from_audiveris.build_parts(recognition)[0]
    assert all(s.bbox is None for s in first.events)
    assert all(s.confidence == from_audiveris.UNKNOWN_CONFIDENCE for s in first.events)


# --- Assemblage -----------------------------------------------------------------------------------


def imported(tmp_path, page_numbers):
    pages = [ImportedPage(page_number=n, kind="scanned", image_path=tmp_path / f"page-{n:03d}.png",
                          width=2480, height=3508, interline=22) for n in page_numbers]
    return ImportedScore(source_path=tmp_path / "partie.pdf", source_kind="scanned_pdf",
                         work_dir=tmp_path, pages=pages)


def test_build_model_from_both_sources(tmp_path):
    """Page 1 vectorielle, page 3 scannée (Audiveris) : une seule partie, dans l'ordre."""
    vector = vector_score([part_page()])
    recognition = make_recognition(tmp_path, page=3)
    recognition.vector = vector
    model = build_model(imported(tmp_path, [1, 3]), recognition)

    assert len(model.parts) == 1
    part = model.parts[0]
    assert [m.page for m in part.measures] == [1, 1, 3, 3]
    assert [m.number for m in part.measures] == [1, 2, 3, 4]
    assert [p.source for p in model.pages] == ["vector", "audiveris"]
    assert model.title == "ZAPATEADO" and part.name == "Flûte"


def test_audiveris_measures_on_vector_pages_are_dropped(tmp_path):
    vector = vector_score([part_page()])
    recognition = make_recognition(tmp_path, page=1)       # Audiveris a aussi lu la page 1
    model = build_model(imported(tmp_path, [1]), recognition, vector)
    assert {m.id[0] for m in model.parts[0].measures} == {"v"}


def test_build_model_vector_only(tmp_path):
    vector = vector_score([part_page()])
    model = build_model(imported(tmp_path, [1]), None, vector)
    assert len(model.parts[0].measures) == 2
    assert all(s.source == "vector" for s in model.symbols())
