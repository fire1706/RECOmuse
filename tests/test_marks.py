"""Tests des signes d'expression : liaisons, articulations, nuances, soufflets et tempo,
de la lecture du MusicXML d'Audiveris jusqu'au rendu, à l'export MusicXML et au MIDI."""

import xml.etree.ElementTree as ET
from fractions import Fraction

from recomuse.export import midi
from recomuse.export.mei import model_to_mei
from recomuse.export.musicxml import model_to_musicxml
from recomuse.model import from_audiveris, marks
from recomuse.model.score import Measure

from validation_helpers import attribute, four_four, measure, model_of, note, rest, treble


def quarters(ident: str, count: int, **value):
    return [note(f"{ident}.n{k}", "C", 5, "1", **value) for k in range(count)]


def with_marks():
    """4 mesures : liaison sur 2 mesures, mf puis soufflet vers f, accent, staccato,
    point d'orgue, et un tempo en mesure 3."""
    m1 = quarters("m1", 4)
    m1[0].value |= {"dynamic": "mf", "slur_start": True}
    m1[1].value |= {"wedge_start": "crescendo", "articulations": ["accent"]}
    m1[3].value["wedge_stop"] = True
    m2 = quarters("m2", 4)
    m2[0].value |= {"dynamic": "f", "slur_stop": True}
    m2[1].value["articulations"] = ["staccato"]
    m3 = quarters("m3", 4)
    m4 = quarters("m4", 4)
    m4[3].value["articulations"] = ["fermata"]
    tempo = attribute("tp", "tempo", text="Allegro", beat="1", per_minute=132)
    return model_of([measure("m1", m1, [treble(), four_four()]), measure("m2", m2),
                     measure("m3", m3, [tempo]), measure("m4", m4)])


# --- Lecture du MusicXML ----------------------------------------------------------------------


def test_note_notations_are_read():
    element = ET.fromstring(
        "<note><pitch><step>C</step><octave>5</octave></pitch><notations>"
        '<slur type="start"/><articulations><accent/><staccato/></articulations>'
        "<fermata/></notations></note>")
    assert from_audiveris._notations(element) == {
        "slur_start": True, "articulations": ["accent", "staccato", "fermata"]}
    assert from_audiveris._notations(ET.fromstring("<note/>")) == {}


def test_tempo_directions():
    allegro = ET.fromstring(
        '<direction placement="above"><direction-type><words>Allegro</words></direction-type>'
        "<direction-type><metronome><beat-unit>quarter</beat-unit><beat-unit-dot/>"
        "<per-minute>88</per-minute></metronome></direction-type></direction>")
    assert from_audiveris._tempo(allegro) == {"text": "Allegro", "beat": "3/2",
                                              "per_minute": 88}
    solo = ET.fromstring('<direction placement="above"><direction-type><words>Solo</words>'
                         "</direction-type></direction>")
    assert from_audiveris._tempo(solo) is None


def test_directions_go_to_the_next_note_and_wedge_ends_on_the_previous():
    measure_ = Measure(id="m", number=1)
    pending: dict = {}
    geometry = from_audiveris._Geometry(page=1, scale=1.0, px_per_tenth=1.0, omr=None)
    dynamic = ET.fromstring("<direction><direction-type><dynamics><mp/></dynamics>"
                            "</direction-type></direction>")
    from_audiveris._read_direction(dynamic, pending, measure_, geometry)
    assert pending == {"dynamic": "mp"}
    measure_.events.append(note("n0", "C", 5))
    stop = ET.fromstring('<direction><direction-type><wedge type="stop"/></direction-type>'
                         "</direction>")
    from_audiveris._read_direction(stop, pending, measure_, geometry)
    assert measure_.events[0].value["wedge_stop"] is True


# --- Liaisons et soufflets -------------------------------------------------------------------


def test_spans_pair_slurs_across_measures_and_close_open_wedges():
    model = with_marks()
    found = marks.spans(model.parts[0])
    assert [(s.kind, s.start.id, s.end.id) for s in found] == [
        ("slur", "m1.n0", "m2.n0"), ("wedge", "m1.n1", "m1.n3")]


def test_an_open_wedge_stops_before_the_next_dynamic():
    m1 = quarters("m1", 4)
    m1[0].value["wedge_start"] = "diminuendo"         # fin jamais lue
    m1[3].value["dynamic"] = "p"
    model = model_of([measure("m1", m1, [treble(), four_four()])])
    [span] = marks.spans(model.parts[0])
    assert (span.start.id, span.end.id, span.form) == ("m1.n0", "m1.n2", "diminuendo")


def test_an_open_wedge_does_not_cross_a_long_rest():
    m1 = quarters("m1", 4)
    m1[1].value["wedge_start"] = "crescendo"
    model = model_of([measure("m1", m1, [treble(), four_four()]),
                      measure("m2", [rest("m2.r", "4", full=True)],
                              [attribute("mr", "multirest", count=8)]),
                      measure("m3", quarters("m3", 4))])
    [span] = marks.spans(model.parts[0])
    assert span.end.id == "m1.n3"


# --- Rendu, MusicXML, MIDI --------------------------------------------------------------------


def test_mei_draws_every_mark():
    mei = model_to_mei(with_marks())["mei"]
    assert '<slur staff="1" startid="#s-m1.n0" endid="#s-m2.n0"/>' in mei
    assert '<hairpin form="cres" staff="1" startid="#s-m1.n1" endid="#s-m1.n3"/>' in mei
    assert '<dynam staff="1" startid="#s-m1.n0">mf</dynam>' in mei
    assert '<artic artic="acc"/>' in mei and '<artic artic="stacc"/>' in mei
    assert '<fermata staff="1" startid="#s-m4.n3"/>' in mei
    assert 'mm="132" mm.unit="4"' in mei and "Allegro" in mei


def test_musicxml_writes_every_mark():
    xml = model_to_musicxml(with_marks())
    ET.fromstring(xml.split("?>", 1)[1].split(">", 1)[1])   # bien formé (sans DOCTYPE)
    for expected in ('<slur type="start" number="1"/>', '<slur type="stop" number="1"/>',
                     "<dynamics><mf/></dynamics>", "<dynamics><f/></dynamics>",
                     '<wedge type="crescendo" number="2"/>', '<wedge type="stop" number="2"/>',
                     "<articulations><accent/></articulations>",
                     "<articulations><staccato/></articulations>", "<fermata/>",
                     "<words>Allegro</words>", "<per-minute>132</per-minute>",
                     '<sound tempo="132"/>'):
        assert expected in xml, expected
    # La nuance est écrite AVANT sa note, la fin du soufflet APRÈS la sienne.
    assert xml.index("<dynamics><mf/>") < xml.index("<pitch>")


def test_midi_plays_dynamics_hairpins_accents_and_staccato():
    part = with_marks().parts[0]
    velocities = midi._velocities(part)
    assert velocities["m1.n0"] == marks.DYNAMICS["mf"]
    # Soufflet de mf vers f, et accent (+15) sur sa première note.
    assert velocities["m1.n1"] == marks.DYNAMICS["mf"] + midi.ACCENT_BOOST["accent"]
    assert marks.DYNAMICS["mf"] < velocities["m1.n2"] < marks.DYNAMICS["f"]
    assert velocities["m2.n0"] == marks.DYNAMICS["f"]
    timeline = midi._timeline(part.measures)
    notes = midi._notes(part.measures, timeline, 0, False, velocities)
    staccato = notes[5]                                   # 2e note de la mesure 2
    assert staccato[1] - staccato[0] == midi.TICKS_PER_QUARTER // 2


def test_a_crescendo_never_goes_down_to_a_misread_dynamic():
    m1 = quarters("m1", 4)
    m1[0].value["dynamic"] = "mf"
    m1[0].value["wedge_start"] = "crescendo"
    m1[1].value["wedge_stop"] = True
    m1[2].value["dynamic"] = "p"                       # la nuance « f » a été manquée
    part = model_of([measure("m1", m1, [treble(), four_four()])]).parts[0]
    assert midi._velocities(part)["m1.n1"] == marks.DYNAMICS["mf"] + midi.WEDGE_STEP


def test_tempo_speeds():
    assert marks.quarters_per_minute({"beat": "3/2", "per_minute": 60}) == 90
    assert marks.quarters_per_minute({"text": "Andante"}) is None
    assert marks.quarters_per_minute({"text": "Andante"}, guess_from_text=True) == 80
    assert marks.beat_unit(Fraction(3, 2)) == ("quarter", True)
