"""Tests des conducteurs : noms des portées, parties extraites, conducteur assemblé, export."""

import xml.etree.ElementTree as ET

import pytest
from test_export import read_midi

from recomuse import library
from recomuse.api import Api
from recomuse.export import files
from recomuse.export.midi import model_to_midi
from recomuse.export.musicxml import model_to_musicxml
from recomuse.instruments.table import load_table
from recomuse.model import conductor
from recomuse.model.score import Part, ScoreModel
from recomuse.model.store import load_model, save_model
from recomuse.vector.primitives import VLine
from recomuse.vector.reader import interpret_page
from recomuse.vector.score import VectorScore

from validation_helpers import attribute, four_four, measure, model_of, note, treble
from vector_builder import BASS, TREBLE, PageBuilder

TABLE = load_table()


# --- Noms des portées ---------------------------------------------------------------------


def conductor_page():
    """Un système de 4 portées : trompette, trombone, piano (2 portées, nom entre les
    deux), et un numéro de mesure (pas un nom) à gauche."""
    page = PageBuilder()
    tops = (100, 140, 180, 220)
    for top in tops:
        page.staff(top, barlines=[])
    for x in (300, 550):
        page.vlines.append(VLine(x, 100, 240, 0.5))     # barres communes : un système
    for k, code in enumerate((TREBLE, BASS, TREBLE, BASS)):
        page.glyph(k, code, 55, 2 if code == TREBLE else 6)
    page.text("Trumpet", 5, 100, 40, 108)
    page.text("in B♭ 1", 5, 109, 40, 117)                # nom sur deux lignes
    page.text("Trombone", 5, 145, 45, 153)
    page.text("Piano", 5, 205, 30, 213)                  # entre les portées 3 et 4
    page.text("17", 30, 125, 40, 133)                    # chiffres seuls : pas un nom
    return page


def test_staff_names_are_read_left_of_the_system():
    score = VectorScore(source_path=None, pages=[interpret_page(conductor_page().build(), 1)])
    assert score.staff_names() == ["Trumpet in B♭ 1", "Trombone", "Piano", "Piano"]


# --- Groupes, extraction, assemblage ------------------------------------------------------


def part(ident: str, name: str | None, clef=None, count: int = 2) -> Part:
    measures = [measure(f"{ident}m{k}", [note(f"{ident}n{k}", "C", 5, "4")],
                        [clef or treble(f"{ident}c"), four_four(f"{ident}t")] if k == 0 else [])
                for k in range(count)]
    return Part(id=ident, name=name, measures=measures)


def read_conductor() -> ScoreModel:
    model = model_of([], name=None)
    model.title, model.tempo = "Marche", "Allegro"
    model.parts = [part("P1", "Trumpet in B♭ 1"), part("P2", "Trombone 1",
                                                        attribute("tc", "clef", sign="F", line=4)),
                   part("P3", "Piano"), part("P4", "Piano"), part("P5", None)]
    model.renumber()
    return model


def test_instrument_groups_and_extraction():
    model = read_conductor()
    groups = conductor.instrument_groups(model)
    assert [[p.id for p in g] for g in groups] == [["P1"], ["P2"], ["P3", "P4"], ["P5"]]
    assert conductor.is_conductor(model) and not conductor.is_conductor(model_of([]))
    extracted = conductor.extract_parts(model)
    assert [(m.instrument, len(m.parts), m.derived) for m in extracted] == [
        ("Trumpet in B♭ 1", 1, "extracted"), ("Trombone 1", 1, "extracted"),
        ("Piano", 2, "extracted"), (None, 1, "extracted")]
    assert extracted[0].title == "Marche" and extracted[0].pages == model.pages
    extracted[0].parts[0].measures[0].events[0].value["octave"] = 6
    assert model.parts[0].measures[0].events[0].value["octave"] == 5    # copie


def test_assembled_conductor_order_ids_and_pages():
    trombone = model_of([], name=None)
    trombone.parts = [part("P1", None, attribute("tc", "clef", sign="F", line=4), count=3)]
    trombone.instrument = "Trombone 1"
    trumpet2, trumpet1 = (model_of([]), model_of([]))
    for model, name in ((trumpet2, "Trumpet 2"), (trumpet1, "Trumpet 1")):
        model.parts = [part("P1", name)]
        model.instrument, model.title = name, "Marche"
    trumpet1.instrument_id, trumpet1.variant_id = "trumpet", "c"
    result = conductor.assemble([(7, trombone), (8, trumpet2), (9, trumpet1)], TABLE)
    # Ordre de la table (trompettes avant trombones), puis par nom.
    assert [p.name for p in result.parts] == ["Trumpet 1", "Trumpet 2", "Trombone 1"]
    assert (result.parts[0].instrument_id, result.parts[0].variant_id) == ("trumpet", "c")
    first = result.parts[0].measures[0]
    assert first.id == "s9-P1m0" and first.events[0].id == "s9-P1n0"
    assert first.page is None and first.events[0].bbox is None and result.pages == []
    assert (result.derived, result.derived_from, result.title) == ("assembled", [7, 8, 9], "Marche")
    assert [m.number for m in result.parts[2].measures] == [1, 2, 3]


# --- Export d'un conducteur ---------------------------------------------------------------


def test_conductor_export_gives_each_part_its_transposition():
    model = read_conductor()
    instruments = files._part_instruments(model, TABLE)
    assert [(i.id if i else None, v.id if v else None) for i, v in instruments] == [
        ("trumpet", "bb"), ("trombone", "c_bass"), ("piano", "c"), (None, None)]
    root = ET.fromstring(model_to_musicxml(model, instruments=instruments).split("\n", 2)[2])
    parts = root.findall("part")
    assert len(parts) == 4                                  # le piano : une partie, 2 portées
    # Le tempo n'est écrit qu'une fois, au-dessus de la première partie.
    assert [len(p.findall("measure/direction/direction-type/words")) for p in parts] == [
        1, 0, 0, 0]
    assert parts[0].findtext("measure/attributes/transpose/chromatic") == "-2"
    assert parts[1].find("measure/attributes/transpose") is None
    assert parts[2].findtext("measure/attributes/staves") == "2"
    programs = [p.findtext("midi-instrument/midi-program")
                for p in root.findall("part-list/score-part")]
    assert programs == ["57", "58", "1", "1"]
    # MIDI : la trompette en si♭ joue un ton plus bas, le trombone comme écrit.
    _, _, tracks = read_midi(model_to_midi(model, instruments=instruments))
    first_note = [next(e[1] for _, e in track if e[0] & 0xF0 == 0x90) for track in tracks[1:]]
    assert first_note[:2] == [70, 72]


# --- Bibliothèque et pont ------------------------------------------------------------------


@pytest.fixture
def stored(conn, score_id):
    with conn:
        conn.execute("UPDATE scores SET title = 'Marche' WHERE id = ?", (score_id,))
    save_model(conn, score_id, read_conductor())
    return score_id


def test_extract_and_assemble_through_the_api(conn, stored):
    api = Api(conn, ":memory:")
    [summary] = [s for s in api.list_scores() if s["score_id"] == stored]
    assert summary["instruments"] == ["Trumpet in B♭ 1", "Trombone 1", "Piano", None]
    extracted = api.extract_parts(stored)["scores"]
    assert [s["instrument"] for s in extracted] == ["Trumpet in B♭ 1", "Trombone 1", "Piano",
                                                   None]
    assert all(s["derived"] == "extracted" for s in extracted)
    assert load_model(conn, extracted[0]["score_id"]).derived_from == [stored]
    assert api.extract_parts(extracted[0]["score_id"]) == {"error": "not_a_conductor"}

    piece = api.get_piece_scores(stored)
    assert {s["score_id"] for s in piece} >= {stored, *(s["score_id"] for s in extracted)}
    ids = [extracted[0]["score_id"], extracted[1]["score_id"]]
    assembled = api.assemble_conductor(ids)["score"]
    assert assembled["derived"] == "assembled" and assembled["pages"] == []
    assert assembled["instruments"] == ["Trumpet in B♭ 1", "Trombone 1"]
    assert api.assemble_conductor(ids[:1]) == {"error": "conductor_needs_parts"}
    assert library.assemble_conductor(conn, [ids[0], 999]) is None
