"""Tests de la table des instruments et de la transposition (instruments/)."""

import pytest

from recomuse.api import Api
from recomuse.instruments import parts
from recomuse.instruments.table import Interval, key_in_name, load_table
from recomuse.instruments.transpose import (
    Request,
    for_instruments,
    simplest_spelling,
    tonic,
    transpose_fifths,
    transpose_model,
    transpose_note,
)
from recomuse.model.store import load_model, save_model
from recomuse.validation import validate

from validation_helpers import attribute, four_four, measure, model_of, note

TABLE = load_table()


def test_intervals():
    assert Interval.parse("P1") == Interval(0, 0)
    assert Interval.parse("M2") == Interval(1, 2)
    assert Interval.parse("m3") == Interval(2, 3)
    assert Interval.parse("-M9") == Interval(-8, -14)
    assert Interval.parse("-M16") == Interval(-15, -26)
    assert Interval.parse("P8") == Interval(7, 12)
    assert Interval.parse("A4") == Interval(3, 6) and Interval.parse("d5") == Interval(4, 6)
    assert Interval.parse("P1") - Interval.parse("-M9") == Interval(8, 14)
    for wrong in ("M5", "P3", "X2", "2"):
        with pytest.raises(ValueError):
            Interval.parse(wrong)


def test_every_instrument_of_the_table_is_readable():
    for instrument in TABLE.instruments:
        assert instrument.label["fr"] and instrument.label["en"] and instrument.variants
        for variant in instrument.variants:
            assert variant.clef in ("G2", "F4", "C3", "C4", "perc")


@pytest.mark.parametrize(("name", "clef", "expected"), [
    ("Trumpet in B♭ 2", "G", ("trumpet", "bb")),
    ("Solo Bb Cornet", "G", ("trumpet", "bb")),
    ("Trompette en ut", "G", ("trumpet", "c")),
    ("Cor 2 en Fa", "G", ("horn", "f")),
    ("Horn in Es", "G", ("horn", "eb")),
    ("Euphonium", "F", ("euphonium", "c_bass")),
    ("Euphonium", "G", ("euphonium", "bb_treble")),
    ("Bass Guitar", "F", ("bass_guitar", "c")),
    ("Basse sib", "G", ("tuba", "bb_treble")),
    ("Tenor Saxophone 2", "G", ("tenor_saxophone", "bb")),
    ("Clarinette en la", "G", ("clarinet", "a")),
    ("Drum Set", "percussion", ("percussion", "perc")),
])
def test_instrument_and_version_are_detected(name, clef, expected):
    instrument, variant = TABLE.detect(name, clef)
    assert (instrument.id, variant.id) == expected


def test_key_in_name():
    assert key_in_name("Klarinette 1 in B") == "Bb"
    assert key_in_name("Cornet en si b") == "Bb"
    assert key_in_name("Mib Alto") == "Eb"
    assert key_in_name("Flûte") is None
    assert TABLE.detect("Ukulélé") is None


def test_notes_and_keys():
    # Do → ré (seconde majeure), fa♯ → sol♯, si♭ → do.
    assert transpose_note("C", 4, 0, Interval(1, 2)) == ("D", 4, 0)
    assert transpose_note("F", 4, 1, Interval(1, 2)) == ("G", 4, 1)
    assert transpose_note("B", 3, -1, Interval(1, 2)) == ("C", 4, 0)
    # Neuvième majeure plus haut (euphonium en ut → en si♭) : fa3 → sol4.
    assert transpose_note("F", 3, 0, Interval(8, 14)) == ("G", 4, 0)
    assert [tonic(f) for f in (-3, 0, 2, 6)] == [("E", -1), ("C", 0), ("D", 0), ("F", 1)]
    assert transpose_fifths(-2, Interval(1, 2)) == 0          # si♭ majeur → do majeur
    assert transpose_fifths(0, Interval(-2, -3)) == 3         # do → la (tierce mineure bas)
    # Si majeur + seconde majeure = do♯ majeur (7 dièses) : on préfère ré♭ (5 bémols).
    spelled = simplest_spelling(Interval(1, 2), [5])
    assert spelled == Interval(2, 2) and transpose_fifths(5, spelled) == -5
    assert simplest_spelling(Interval(1, 2), [0, 2]) == Interval(1, 2)


def euphonium_part():
    """Euphonium en ut, clé de fa, si♭ majeur : fa3, si♭2."""
    return model_of([
        measure("m1", [note("n1", "F", 3, "2"), note("n2", "B", 2, "2", alter=-1)],
                [attribute("c", "clef", sign="F", line=4), attribute("k", "key", fifths=-2),
                 four_four()]),
        measure("m2", [note("n3", "D", 3, "4")])], name="Euphonium")


def test_part_rewritten_for_another_instrument():
    """Euphonium en ut (clé de fa) → baryton en si♭ (clé de sol) : neuvième au-dessus."""
    euphonium = TABLE.get("euphonium")
    request = for_instruments(euphonium.variant("c_bass"), euphonium,
                              euphonium.variant("bb_treble"))
    original = euphonium_part()
    result, report = transpose_model(original, request)
    notes = {s.id: (s.value["step"], s.value["octave"], s.value["alter"])
             for s in result.symbols() if s.kind == "note"}
    assert notes == {"n1": ("G", 4, 0), "n2": ("C", 4, 0), "n3": ("E", 4, 0)}
    attrs = {s.kind: s.value for s in result.parts[0].measures[0].attributes}
    assert attrs["clef"] == {"sign": "G", "line": 2, "octave_change": 0}
    assert attrs["key"] == {"fifths": 0}
    assert all(s.source == "transposed" for s in result.symbols() if s.kind == "note")
    assert (result.instrument_id, result.variant_id) == ("euphonium", "bb_treble")
    assert report["keys"] == [0] and report["out_of_range"] == 0
    assert report["suggested_octave"] == 0 and report["notes"] == 3
    # L'original n'a pas bougé ; la partie transposée ne déclenche aucun doute de hauteur.
    assert original.find("n1")[2].value["step"] == "F"
    assert validate(result).by_code("note_position_mismatch") == []


def test_octave_is_suggested_when_the_part_does_not_fit():
    """Partie de flûte réécrite pour un tuba en clé de fa, sans octave : beaucoup trop
    aiguë, deux octaves plus bas sont conseillées."""
    flute = model_of([measure("m1", [note(f"n{k}", "C", 6, "1") for k in range(4)],
                              [attribute("c", "clef", sign="G", line=2), four_four()])],
                     name="Flûte")
    tuba = TABLE.get("tuba")
    request = for_instruments(TABLE.get("flute").variant("c"), tuba, tuba.variant("c_bass"))
    _, report = transpose_model(flute, request)
    assert report["out_of_range"] == 4 and report["suggested_octave"] == -2
    with pytest.raises(ValueError):
        for_instruments(TABLE.get("percussion").variant("perc"), tuba, tuba.variant("c_bass"))


def test_transposition_by_interval_keeps_clef_and_percussion():
    model = euphonium_part()
    result, report = transpose_model(model, Request(Interval(-1, -2), octave=1))
    # Seconde majeure plus bas et une octave plus haut : fa3 → mi♭4.
    n1 = result.find("n1")[2].value
    assert (n1["step"], n1["octave"], n1["alter"]) == ("E", 4, -1)
    assert result.find("c")[2].value["sign"] == "F"            # la clé ne change pas
    assert report["keys"] == [-4]                               # la♭ majeur
    drums = model_of([measure("m1", [note("d", "C", 5, "1")],
                              [attribute("c", "clef", sign="percussion")])])
    unchanged, _ = transpose_model(drums, Request(Interval(1, 2)))
    assert unchanged.find("d")[2].value["step"] == "C"


@pytest.fixture
def stored(conn, score_id):
    save_model(conn, score_id, euphonium_part())
    return score_id


def test_transposed_score_is_a_new_score(conn, stored):
    request = {"mode": "instrument", "target": {"instrument": "euphonium", "variant": "bb_treble"},
               "name": "Baryton si♭"}
    assert parts.check(conn, stored, request)["keys"] == [0]
    result = parts.transpose_score(conn, stored, request)
    new_id = result["score"]["score_id"]
    assert new_id != stored and result["score"]["instrument"] == "Baryton si♭"
    copy = load_model(conn, new_id)
    assert copy.transposed_from == stored and copy.find("n1")[2].value["octave"] == 4
    assert load_model(conn, stored).find("n1")[2].value["octave"] == 3
    row = conn.execute("SELECT part_name, source_path FROM scores WHERE id = ?",
                       (new_id,)).fetchone()
    assert row[0] == "Baryton si♭" and row[1] == "fictif/partie.pdf"


def test_instrument_of_a_score_and_user_choice(conn, stored):
    model = load_model(conn, stored)
    assert parts.instrument_of(model) == {"instrument_id": "euphonium", "variant_id": "c_bass",
                                          "detected": True}
    chosen = parts.set_instrument(conn, stored, "trombone", "c_bass")
    assert chosen == {"instrument_id": "trombone", "variant_id": "c_bass", "detected": False}
    with pytest.raises(parts.TranspositionError):
        parts.set_instrument(conn, stored, "trombone", "inconnu")


def test_api_instrument_methods(conn, stored):
    api = Api(conn, ":memory:")
    table = api.get_instruments()
    euphonium = next(i for i in table if i["id"] == "euphonium")
    assert [v["id"] for v in euphonium["variants"]] == ["bb_treble", "c_bass"]
    assert next(i for i in table if i["id"] == "percussion")["variants"][0]["transposable"] is False
    assert api.get_score_instrument(stored)["instrument_id"] == "euphonium"
    report = api.check_transposition(stored, {"mode": "interval", "interval": "M2",
                                              "direction": "up", "octave": 0})
    assert report["keys"] == [0]
    for wrong in ({"mode": "interval", "interval": "Z9"}, {"mode": "?"},
                  {"mode": "instrument", "target": {"instrument": "tuba", "variant": "x"}},
                  {"mode": "interval", "interval": "M2", "octave": 9}):
        assert api.check_transposition(stored, wrong) == {"error": "transposition_failed"}
    created = api.transpose_score(stored, {"mode": "interval", "interval": "P8",
                                           "direction": "down", "name": "Euphonium grave"})
    assert created["score"]["instrument"] == "Euphonium grave"
    assert api.get_score_instrument(999) == {"error": "transposition_failed"}
