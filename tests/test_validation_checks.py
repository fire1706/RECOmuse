"""Tests des contrôles du validateur : durées, hauteurs, pauses multiples, numéros, tessiture."""

from fractions import Fraction

import numpy as np
import pytest

from recomuse.instruments.table import load_table, midi_number, parse_note
from recomuse.validation.durations import check_durations, meter_of
from recomuse.validation.geometry import PageGeometries, find_staves
from recomuse.validation.numbering import (
    check_multirests,
    check_numbering,
    find_hbar,
    tight_number,
)
from recomuse.validation.pitches import check_pitches, expected_pitch
from recomuse.validation.ranges import check_ranges

from validation_helpers import (
    INTERLINE,
    STAFF_TOP,
    attribute,
    four_four,
    measure,
    model_of,
    note,
    page_image,
    rest,
    treble,
)


def codes(issues):
    return [i.code for i in issues]


# --- Durées -----------------------------------------------------------------------------------


def quarter_notes(prefix: str, count: int):
    return [note(f"{prefix}{k}", "C", 5) for k in range(count)]


def test_correct_measures_have_no_issue():
    model = model_of([measure("m1", quarter_notes("a", 4), [treble(), four_four()]),
                      measure("m2", quarter_notes("b", 4))])
    assert check_durations(model) == []


def test_isolated_wrong_measure():
    model = model_of([measure("m1", quarter_notes("a", 4), [four_four()]),
                      measure("m2", quarter_notes("b", 5))])
    issues = check_durations(model)
    assert codes(issues) == ["measure_duration"]
    assert issues[0].measure_numbers == [2]
    assert issues[0].details == {"read": "5", "expected": "4"}
    assert len(issues[0].symbol_ids) == 5


def test_pickup_is_not_an_error():
    model = model_of([measure("m1", quarter_notes("a", 1), [four_four()]),
                      measure("m2", quarter_notes("b", 4))])
    assert check_durations(model) == []


def test_missed_time_signature_change():
    """3 mesures de suite qui durent toutes 3 temps en 4/4 : un 3/4 a été manqué."""
    measures = [measure("m1", quarter_notes("a", 4), [four_four()])]
    measures += [measure(f"m{k}", quarter_notes(f"x{k}", 3)) for k in (2, 3, 4)]
    issues = check_durations(model_of(measures))
    assert codes(issues) == ["time_signature_missed"]
    assert issues[0].measure_numbers == [2, 3, 4]
    assert issues[0].details["proposed"] == "3/4"
    assert issues[0].action == {"insert_time": "3/4", "before_measure": 2}


def test_wrong_time_signature_gets_a_fix():
    """Le chiffrage est lu au bon endroit mais faux (4/4 au lieu de 3/4) : on corrige."""
    measures = [measure(f"m{k}", quarter_notes(f"x{k}", 3), [four_four()] if k == 1 else [])
                for k in (1, 2, 3)]
    issues = check_durations(model_of(measures))
    assert codes(issues) == ["time_signature_missed"]
    assert issues[0].fixes[0].symbol_id == "t"
    assert issues[0].fixes[0].value == {"beats": 3, "beat_type": 4}


def test_missing_time_signature():
    measures = [measure(f"m{k}", quarter_notes(f"x{k}", 3), expected=None) for k in range(4)]
    issues = check_durations(model_of(measures))
    assert codes(issues) == ["time_signature_missing"]
    assert issues[0].details["proposed"] == "3/4"


def test_missing_time_signature_without_enough_evidence():
    measures = [measure("m0", quarter_notes("a", 3), expected=None),
                measure("m1", quarter_notes("b", 5), expected=None)]
    issues = check_durations(model_of(measures))
    assert codes(issues) == ["time_signature_missing"]
    assert issues[0].details["proposed"] is None and issues[0].action == {}
    assert issues[0].confidence == 0.3


def test_rests_multirests_and_percussion_are_not_checked():
    model = model_of([
        measure("m1", quarter_notes("a", 4), [four_four()]),
        measure("m2", [rest("r", "4", full=True)]),
        measure("m3", [], [attribute("mr", "multirest", count=8)]),
        measure("m4", quarter_notes("p", 7),
                [attribute("pc", "clef", sign="percussion", line=None)]),
    ])
    assert check_durations(model) == []


@pytest.mark.parametrize(("duration", "meter"), [(Fraction(3), "3/4"), (Fraction(3, 2), "3/8"),
                                                 (Fraction(9, 2), "9/8"), (Fraction(5, 4), "5/16")])
def test_meter_of(duration, meter):
    assert meter_of(duration) == meter


# --- Hauteurs -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("clef", "position", "expected"), [
    ({"sign": "G", "line": 2}, 0, ("E", 4)),
    ({"sign": "G", "line": 2, "octave_change": -1}, 0, ("E", 3)),
    ({"sign": "F", "line": 4}, 8, ("A", 3)),
    ({"sign": "C", "line": 3}, 4, ("C", 4)),
    ({"sign": "percussion", "line": None}, 4, None),
])
def test_expected_pitch(clef, position, expected):
    assert expected_pitch(clef, position) == expected


def test_suspicious_octave_clef_fixes_all_its_notes():
    clef = treble("c", octave_change=-1, confidence=0.26)
    model = model_of([measure("m1", [note("n1", "B", 3), note("n2", "C", 4)], [clef, four_four()]),
                      measure("m2", [note("n3", "D", 4)] * 1)])
    issue = next(i for i in check_pitches(model) if i.code == "clef_octave_suspicious")
    assert issue.confidence == pytest.approx(0.74)
    assert [(f.symbol_id, f.value) for f in issue.fixes] == [
        ("c", {"octave_change": 0}), ("n1", {"octave": 4}), ("n2", {"octave": 5}),
        ("n3", {"octave": 5})]


def test_sure_or_vector_octave_clefs_are_trusted():
    for clef in (treble("c", octave_change=-1, confidence=0.95),
                 treble("c", octave_change=-1, confidence=0.2, source="vector")):
        model = model_of([measure("m1", [note("n1", "B", 3)], [clef])])
        assert "clef_octave_suspicious" not in codes(check_pitches(model))


def test_position_on_the_staff_reveals_a_wrong_octave(tmp_path):
    """Do6 (2e ligne supplémentaire au-dessus) lu do5 : erreur du test de faisabilité."""
    image = page_image(tmp_path / "page.png")
    events = [note("ok", "B", 4, position=4, x=300), note("bad", "C", 5, position=12, x=400)]
    model = model_of([measure("m1", events, [treble(), four_four()])], image)
    issues = check_pitches(model)
    assert codes(issues) == ["note_position_mismatch"]
    assert issues[0].symbol_ids == ["bad"]
    assert issues[0].details["from_position"] == "C6"
    assert issues[0].fixes[0].value == {"step": "C", "octave": 6}
    assert issues[0].severity == "error"          # même note, autre octave


def test_misaligned_measure_is_not_reported_note_by_note(tmp_path):
    """Toutes les notes d'une mesure décalées d'une position : appariement raté, pas
    quatre fausses notes."""
    image = page_image(tmp_path / "page.png")
    events = [note(f"n{k}", "C", 5, position=p, x=300 + 60 * k) for k, p in enumerate((3, 4, 6, 7))]
    model = model_of([measure("m1", events, [treble()])], image)
    assert check_pitches(model) == []


def test_vector_notes_are_not_checked(tmp_path):
    image = page_image(tmp_path / "page.png")
    model = model_of([measure("m1", [note("v", "C", 5, position=12, source="vector")], [treble()])],
                     image)
    assert check_pitches(model) == []


def test_find_staves_in_an_image(tmp_path):
    from recomuse.importer.loading import read_gray

    staves = find_staves(read_gray(page_image(tmp_path / "page.png")))
    assert len(staves) == 1
    assert staves[0].top == pytest.approx(STAFF_TOP, abs=0.5)
    assert staves[0].interline == pytest.approx(INTERLINE, abs=0.2)


# --- Pauses multiples et numéros ---------------------------------------------------------


def test_find_hbar(tmp_path):
    from recomuse.importer.loading import read_gray

    gray = read_gray(page_image(tmp_path / "page.png", hbar=(500, 800)))
    staff = PageGeometries().staves(str(tmp_path / "page.png"))[0]
    assert find_hbar(gray, staff, 400, 900) == pytest.approx((500, 800), abs=2)
    assert find_hbar(gray, staff, 900, 1400) is None


def multirest_measure(count, source="audiveris", bbox=(500, 196, 300, 30)):
    symbol = attribute("mr", "multirest", source=source, count=count)
    symbol.bbox = bbox
    return measure("m2", [rest("r", "4", full=True)], [symbol])


def test_multirest_counted_as_one_is_reread(tmp_path):
    image = page_image(tmp_path / "page.png", hbar=(500, 800))
    model = model_of([measure("m1", quarter_notes("a", 4), [four_four()]),
                      multirest_measure(1)], image)
    issues = check_multirests(model, PageGeometries(), read_number=lambda crop: 12)
    assert codes(issues) == ["multirest_missed"]
    assert issues[0].fixes[0].value == {"count": 12}
    assert issues[0].details["read_by_audiveris"] == 1


def test_multirest_count_unreadable(tmp_path):
    image = page_image(tmp_path / "page.png", hbar=(500, 800))
    model = model_of([multirest_measure(None)], image)
    issues = check_multirests(model, PageGeometries(), read_number=lambda crop: None)
    assert codes(issues) == ["multirest_count_unknown"]


def test_rest_measure_with_a_bar_is_a_missed_multirest(tmp_path):
    """Audiveris n'a vu qu'une pause : l'image montre une barre de pause multiple."""
    image = page_image(tmp_path / "page.png", hbar=(500, 800))
    whole = rest("r", "4", full=True)
    whole.bbox = (630, 205, 40, 10)
    rests = measure("m1", [whole], bbox=(450, 200, 400, 80))
    model = model_of([rests], image)
    issues = check_multirests(model, PageGeometries(), read_number=lambda crop: 5)
    assert codes(issues) == ["multirest_missed"]
    assert issues[0].action == {"set_multirest": 5, "measure_id": "m1"}


def test_multirests_of_the_vector_reading_are_trusted(tmp_path):
    image = page_image(tmp_path / "page.png", hbar=(500, 800))
    model = model_of([multirest_measure(1, source="vector")], image, source="vector")
    assert check_multirests(model, PageGeometries(), read_number=lambda crop: 12) == []


def numbered(ident, printed, events, system):
    m = measure(ident, events, printed_number=printed, system=system)
    return m


def test_numbering_jump_points_to_the_rest_measure():
    """Lignes numérotées 1, 9, 13 ; entre 1 et 9, une seule mesure de pause : c'est une
    pause multiple comptée pour une (il manque 5 mesures)."""
    lines = [
        [numbered("a1", 1, quarter_notes("a", 4), 0),
         measure("a2", [rest("r", "4", full=True)], system=0),
         measure("a3", quarter_notes("c", 4), system=0)],
        [numbered("b1", 9, quarter_notes("d", 4), 1),
         measure("b2", quarter_notes("e", 4), system=1),
         measure("b3", quarter_notes("f", 4), system=1),
         measure("b4", quarter_notes("g", 4), system=1)],
        [numbered("c1", 13, quarter_notes("h", 4), 2)],
    ]
    model = model_of([m for line in lines for m in line])
    issues = check_numbering(model, PageGeometries())
    assert codes(issues) == ["measure_number_mismatch"]
    # La ligne 2 commence à 9 : il faut 8 mesures avant elle, il n'y en a que 3.
    assert issues[0].details["missing"] == 5
    assert issues[0].action == {"set_multirest": 6, "measure_id": "a2"}


def test_big_unexplained_numbering_jump_is_ignored():
    """Un numéro mal lu (70 au lieu de 7) ne doit pas déclencher d'alerte."""
    lines = [numbered("a", 1, quarter_notes("a", 4), 0),
             numbered("b", 70, quarter_notes("b", 4), 1),
             numbered("c", 71, quarter_notes("c", 4), 2)]
    assert check_numbering(model_of(lines), PageGeometries()) == []


def test_tight_number_crop():
    crop = np.full((80, 200), 255, np.uint8)
    crop[20:50, 90:110] = 0                       # le « chiffre »
    crop[5:8, 0:10] = 0                           # une tache loin du centre
    piece = tight_number(crop, interline=20, center=100)
    assert piece.shape == ((30 + 24) * 2, (20 + 24) * 2)


# --- Tessiture ----------------------------------------------------------------------------------


def test_instrument_table():
    table = load_table()
    assert table.find("Solo Bb Cornet").id == "trumpet"
    assert table.find("Klarinette 2 in B").id == "clarinet"
    assert table.find("Clarinette basse").id == "bass_clarinet"
    assert table.find("Alto Saxophone 1").id == "saxophone"
    assert table.find("Cor 2 en Fa").id == "horn"
    assert table.find("Vocals") is None
    assert parse_note("Bb3") == midi_number("B", -1, 3) == 58
    assert parse_note("C4") == 60


def test_note_out_of_range_proposes_an_octave():
    model = model_of([measure("m1", [note("low", "C", 3), note("ok", "C", 5)], [treble()])],
                     name="Alto Saxophone")
    issues = check_ranges(model)
    assert codes(issues) == ["note_out_of_range"]
    assert issues[0].details["direction"] == "low"
    assert issues[0].fixes[0].value == {"octave": 4}


def test_unknown_instrument_is_not_checked():
    model = model_of([measure("m1", [note("low", "C", 1)], [treble()])], name="Ukulélé")
    assert check_ranges(model) == []
