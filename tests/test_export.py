"""Tests des exports : MusicXML, MIDI à la hauteur réelle, MuseScore (export/)."""

import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from recomuse.api import Api
from recomuse.export import files, musescore
from recomuse.export.midi import TICKS_PER_QUARTER, model_to_midi, tempo_of
from recomuse.export.musicxml import model_to_musicxml
from recomuse.instruments.table import load_table
from recomuse.model.score import Part
from recomuse.model.store import save_model

from validation_helpers import attribute, four_four, measure, model_of, note, rest, treble

FAKE_MUSESCORE = Path(__file__).parent / "fakes" / "fake_musescore.py"
TABLE = load_table()
TRUMPET = TABLE.get("trumpet")


def sample():
    """Trompette en si♭, ré majeur 4/4 : triolet de croches + noire liée à la mesure
    suivante, deux voix ; pause de 3 mesures ; changement 3/4 ; mesure vide."""
    m1 = measure("m1", [note(f"t{k}", "D", 5, "1/3", tuplet=[3, 2]) for k in range(3)]
                 + [note("half", "C", 5, "2"), note("tie", "F", 5, "1", alter=1, tie_start=True),
                    note("v2", "A", 4, "4", voice=2)],
                 [treble(), attribute("k", "key", fifths=2), four_four()], marks=["A"])
    m2 = measure("m2", [note("end", "F", 5, "1", alter=1, tie_stop=True),
                        note("ch", "A", 5, "1", chord=True), rest("r", "2")])
    m3 = measure("m3", [], [attribute("mr", "multirest", count=3)])
    m4 = measure("m4", [note("d", "E", 5, "3/2", dots=1), note("e", "F", 5, "1/2", alter=0),
                        note("g", "G", 5, "1", grace=True)],
                 [attribute("t2", "time", beats=3, beat_type=4)])
    m5 = measure("m5", [])
    model = model_of([m1, m2, m3, m4, m5], name="Trumpet in B♭")
    model.title, model.composers, model.tempo = "Marche & Cie", ["A. Dupont"], "♩ = 120"
    return model


def parse(text: str) -> ET.Element:
    return ET.fromstring(text.split("\n", 2)[2])     # sans la déclaration ni le DOCTYPE


# --- MusicXML -----------------------------------------------------------------------------


def test_musicxml_header_parts_and_transposition():
    root = parse(model_to_musicxml(sample(), TRUMPET, TRUMPET.variant("bb")))
    assert root.get("version") == "4.0"
    assert root.findtext("work/work-title") == "Marche & Cie"
    assert root.findtext("identification/creator") == "A. Dupont"
    part = root.find("part-list/score-part")
    assert part.findtext("part-name") == "Trumpet in B♭"
    assert part.findtext("midi-instrument/midi-program") == "57"
    attributes = root.find("part/measure/attributes")
    assert attributes.findtext("divisions") == "6"          # triolets et croches pointées
    assert attributes.findtext("key/fifths") == "2"
    assert (attributes.findtext("time/beats"), attributes.findtext("time/beat-type")) == ("4", "4")
    assert (attributes.findtext("clef/sign"), attributes.findtext("clef/line")) == ("G", "2")
    # Trompette en si♭ : sonne une seconde majeure plus bas que l'écrit.
    assert (attributes.findtext("transpose/diatonic"),
            attributes.findtext("transpose/chromatic")) == ("-1", "-2")
    words = root.find("part/measure/direction/direction-type/words")
    assert words.text == "♩ = 120"
    assert root.find("part/measure/direction/direction-type/rehearsal").text == "A"


def test_musicxml_notes():
    root = parse(model_to_musicxml(sample()))
    first = root.find("part/measure")
    notes = first.findall("note")
    triplet = notes[0]
    assert triplet.findtext("duration") == "2" and triplet.findtext("type") == "eighth"
    assert triplet.findtext("time-modification/actual-notes") == "3"
    assert triplet.find("notations/tuplet").get("type") == "start"
    assert notes[2].find("notations/tuplet").get("type") == "stop"
    tied = notes[4]
    assert tied.find("tie").get("type") == "start" and tied.find("notations/tied") is not None
    assert tied.find("accidental") is None                  # fa♯ par l'armure
    # Deuxième voix : retour au début de la mesure.
    backup = first.find("backup")
    assert backup.findtext("duration") == "24"              # 4 noires × 6 divisions
    assert notes[-1].findtext("voice") == "2" and notes[-1].findtext("type") == "whole"

    second = root.findall("part/measure")[1].findall("note")
    assert second[0].find("tie").get("type") == "stop"
    assert second[1].find("chord") is not None
    assert second[2].find("rest") is not None and second[2].findtext("type") == "half"


def test_musicxml_multirest_changes_and_empty_measure():
    root = parse(model_to_musicxml(sample()))
    measures = root.findall("part/measure")
    assert [m.get("number") for m in measures] == ["1", "2", "3", "4", "5", "6", "7"]
    assert measures[2].findtext("attributes/measure-style/multiple-rest") == "3"
    assert all(m.find("note/rest").get("measure") == "yes" for m in measures[2:5])
    fourth = measures[5]
    assert fourth.findtext("attributes/time/beats") == "3"
    dotted, natural, grace = fourth.findall("note")
    assert dotted.findtext("type") == "quarter" and len(dotted.findall("dot")) == 1
    assert natural.findtext("accidental") == "natural"      # fa naturel en ré majeur
    assert grace.find("grace") is not None and grace.find("duration") is None
    empty = measures[6].find("note")
    assert empty.find("rest").get("measure") == "yes" and empty.findtext("duration") == "18"


def test_musicxml_piano_on_two_staves():
    upper = model_of([measure("u1", [note("u", "C", 5, "4")], [treble(), four_four()])],
                     name="Piano")
    lower = [measure("l1", [note("l", "C", 3, "4")], [attribute("bc", "clef", sign="F", line=4)])]
    upper.parts.append(Part(id="P2", name="Piano", measures=lower))
    root = parse(model_to_musicxml(upper))
    assert len(root.findall("part")) == 1
    attributes = root.find("part/measure/attributes")
    assert attributes.findtext("staves") == "2"
    assert [c.get("number") for c in attributes.findall("clef")] == ["1", "2"]
    notes = root.findall("part/measure/note")
    assert [(n.findtext("staff"), n.findtext("voice")) for n in notes] == [("1", "1"), ("2", "5")]


# --- MIDI ---------------------------------------------------------------------------------


def read_midi(data: bytes):
    """Lecture simple d'un fichier MIDI : en-tête et, pour chaque piste, ses événements
    (tic absolu, octets)."""
    kind, length, fmt, ntracks, division = struct.unpack(">4sIHHH", data[:14])
    assert kind == b"MThd" and length == 6
    tracks, pos = [], 14
    for _ in range(ntracks):
        tag, size = struct.unpack(">4sI", data[pos:pos + 8])
        assert tag == b"MTrk"
        body, pos = data[pos + 8:pos + 8 + size], pos + 8 + size
        events, i, now = [], 0, 0
        while i < len(body):
            delta = 0
            while True:
                byte = body[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if byte < 0x80:
                    break
            now += delta
            status = body[i]
            if status == 0xFF:
                size_meta = body[i + 2]
                events.append((now, body[i:i + 3 + size_meta]))
                i += 3 + size_meta
            elif status & 0xF0 == 0xC0:
                events.append((now, body[i:i + 2]))
                i += 2
            else:
                events.append((now, body[i:i + 3]))
                i += 3
        tracks.append(events)
    return fmt, division, tracks


def test_midi_plays_at_concert_pitch():
    data = model_to_midi(sample(), TRUMPET, TRUMPET.variant("bb"))
    fmt, division, (conductor, track) = read_midi(data)
    assert (fmt, division) == (1, TICKS_PER_QUARTER)
    tempo = next(e for t, e in conductor if e[:2] == b"\xff\x51")
    assert int.from_bytes(tempo[3:], "big") == 500_000      # 120 à la noire
    signatures = [(t, e[3]) for t, e in conductor if e[:2] == b"\xff\x58"]
    assert signatures == [(0, 4), (TICKS_PER_QUARTER * (4 + 4 + 12), 3)]
    assert (0, bytes([0xC0, 56])) in track                    # trompette (57 - 1)
    ons = [(t, e[1]) for t, e in track if e[0] & 0xF0 == 0x90]
    assert (0, 67) in ons                                     # 2e voix : la4 → sol4
    ons = [on for on in ons if on != (0, 67)]
    # Ré5 écrit = do5 joué (72) ; les trois croches de triolet tombent sur 0, 160, 320.
    assert ons[:3] == [(0, 72), (160, 72), (320, 72)]
    # Fa♯5 écrit lié = mi5 joué (76) : une seule note, de la 4e noire jusqu'au milieu de m2.
    assert [t for t, p in ons if p == 76] == [480 * 3]
    offs = {(e[1], t) for t, e in track if e[0] & 0xF0 == 0x80}
    assert (76, 480 * 5) in offs
    assert (79, 480 * 4) in {(p, t) for t, p in ons}          # accord la5 → sol5
    # Petite note (sol5) non jouée ; la mesure 3/4 commence après la pause de 3 mesures.
    assert (480 * 20, 74) in ons and all(p != 77 or t != 480 * 22 for t, p in ons)


def test_midi_percussion_and_tempo_text():
    hits = [note("x", None, None, "1", head="x"), note("s", None, None, "3")]
    drums = model_of([measure("m1", hits, [attribute("c", "clef", sign="percussion"),
                                           four_four()])], name="Drum Set")
    _, _, (_, track) = read_midi(model_to_midi(drums))
    assert [(e[0], e[1]) for _, e in track if e[0] & 0xF0 == 0x90] == [(0x99, 42), (0x99, 38)]
    assert tempo_of("Allegro") == 100 and tempo_of("♩ = 92") == 92
    assert tempo_of("♩ = 900") == 100


# --- MuseScore et fichiers ----------------------------------------------------------------


@pytest.fixture
def fake_musescore(monkeypatch, tmp_path):
    """Remplace MuseScore par tests/fakes/fake_musescore.py (mêmes arguments)."""
    launcher = tmp_path / "musescore.cmd" if sys.platform == "win32" else tmp_path / "musescore"
    if sys.platform == "win32":
        launcher.write_text(f'@"{sys.executable}" "{FAKE_MUSESCORE}" %*\n', encoding="utf-8")
    else:
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_MUSESCORE}" "$@"\n')
        launcher.chmod(0o755)
    monkeypatch.setenv("RECOMUSE_MUSESCORE", str(launcher))
    return launcher


@pytest.fixture
def stored(conn, score_id):
    save_model(conn, score_id, sample())
    return score_id


def test_find_musescore_from_environment(fake_musescore):
    assert musescore.find_musescore() == fake_musescore


def test_export_all_formats(conn, stored, tmp_path, fake_musescore):
    xml = files.export_score(conn, stored, "musicxml", tmp_path / "out" / "partie")
    assert xml == {"path": str(tmp_path / "out" / "partie.musicxml"), "format": "musicxml",
                   "fallback": None}
    assert parse(Path(xml["path"]).read_text(encoding="utf-8")).tag == "score-partwise"
    mid = files.export_score(conn, stored, "midi", tmp_path / "partie.mid")
    assert Path(mid["path"]).read_bytes()[:4] == b"MThd"
    mscz = files.export_score(conn, stored, "musescore", tmp_path / "partie.mscz")
    assert mscz["fallback"] is None and mscz["format"] == "musescore"
    with zipfile.ZipFile(mscz["path"]) as archive:
        # La trompette est reconnue d'après le nom : transposition écrite pour MuseScore.
        content = archive.read("partition.musicxml").decode("utf-8")
    assert "<chromatic>-2</chromatic>" in content
    with pytest.raises(files.ExportError):
        files.export_score(conn, stored, "pdf", tmp_path / "x")
    with pytest.raises(files.ExportError):
        files.export_score(conn, stored + 99, "midi", tmp_path / "x")


def test_musescore_missing_or_failing_gives_musicxml(conn, stored, tmp_path, monkeypatch,
                                                     fake_musescore):
    monkeypatch.setenv("FAKE_MUSESCORE_FAIL", "1")
    result = files.export_score(conn, stored, "musescore", tmp_path / "a.mscz")
    assert result == {"path": str(tmp_path / "a.musicxml"), "format": "musicxml",
                      "fallback": "musescore_failed"}
    monkeypatch.setattr(files, "find_musescore", lambda: None)
    result = files.export_score(conn, stored, "musescore", tmp_path / "b.mscz")
    assert result["fallback"] == "musescore_not_found" and Path(result["path"]).is_file()


def test_default_name():
    model = sample()
    model.instrument = 'Trompette 1/2 "solo"'
    assert files.default_name(model) == "Marche & Cie - Trompette 1_2 _solo_"
    assert files.default_name(model_of([])) == "Partition"


def test_api_export_methods(conn, stored, tmp_path, fake_musescore):
    api = Api(conn, ":memory:")
    options = api.get_export_options(stored)
    assert options["default_name"] == "Marche & Cie - Trumpet in B♭"
    assert options["musescore"] is True and options["questions"] >= 0
    assert api.choose_save_path("Partition", "x", "midi") is None     # pas de fenêtre
    result = api.export_score(stored, "midi", str(tmp_path / "x.mid"))
    assert result["format"] == "midi"
    assert api.export_score(stored, "pdf", str(tmp_path / "x")) == {"error": "unknown_format"}
    assert api.get_export_options(999) == {"error": "score_not_found"}


@pytest.mark.external
def test_real_musescore_reads_the_export(conn, stored, tmp_path):
    """Le vrai MuseScore ouvre le MusicXML exporté et écrit un .mscz."""
    if musescore.find_musescore() is None:
        pytest.skip("MuseScore absent")
    result = files.export_score(conn, stored, "musescore", tmp_path / "vrai.mscz")
    assert result["fallback"] is None
    with zipfile.ZipFile(result["path"]) as archive:
        assert any(name.endswith(".mscx") for name in archive.namelist())
