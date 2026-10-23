"""Tests du MEI produit pour l'affichage par Verovio (export/mei.py)."""

import xml.etree.ElementTree as ET

from recomuse.export.mei import model_to_mei
from recomuse.model.score import Part

from validation_helpers import attribute, four_four, measure, model_of, note, rest, treble

NS = {"mei": "http://www.music-encoding.org/ns/mei"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def parse(model):
    result = model_to_mei(model)
    return ET.fromstring(result["mei"].split("\n", 1)[1]), result


def sample():
    """Fa majeur 4/4 : noire si♭ (armure), si bécarre, si (bécarre encore en vigueur),
    accord, triolet de croches ; pause de 8 ; changement 3/4 et clé de fa."""
    m1 = measure("m1", [note("n1", "B", 4, "1", alter=-1),
                        note("n2", "B", 4, "1", alter=0),
                        note("n3", "B", 4, "1", alter=0, tie_start=True),
                        note("n4", "C", 5, "1", chord=True)],
                 [treble(), attribute("k", "key", fifths=-1), four_four()])
    m2 = measure("m2", [note(f"t{k}", "D", 5, "1/3", tuplet=[3, 2]) for k in range(3)]
                 + [note("d", "E", 5, "3", dots=1)])
    m3 = measure("m3", [], [attribute("mr", "multirest", count=8)])
    m4 = measure("m4", [rest("r1", "3", full=True)],
                 [attribute("c2", "clef", sign="F", line=4),
                  attribute("t2", "time", beats=3, beat_type=4)])
    return model_of([m1, m2, m3, m4], name="Trombone 1")


def test_structure_and_identifiers():
    model = sample()
    model.title = "Marche & Cie"
    root, result = parse(model)
    assert root.find(".//mei:title", NS).text == "Marche & Cie"
    staff_def = root.find(".//mei:staffDef", NS)
    assert staff_def.get("clef.shape") == "G" and staff_def.get("key.sig") == "1f"
    assert root.find(".//mei:scoreDef", NS).get("meter.count") == "4"
    assert staff_def.get("label") == "Trombone 1"
    measures = root.findall(".//mei:measure", NS)
    assert [m.get("n") for m in measures] == ["1", "2", "3", "11"]   # pause de 8 : 3 à 10
    # Chaque identifiant MEI renvoie au modèle (« + » n'est pas permis dans un nom XML).
    assert result["measures"][measures[0].get(XML_ID)] == "m1"
    ids = {result["symbols"][e.get(XML_ID)] for e in root.iter() if e.get(XML_ID) in
           result["symbols"]}
    assert {"n1", "n4", "t0", "mr", "r1"} <= ids


def test_notes_accidentals_chords_and_tuplets():
    root, result = parse(sample())
    notes = {result["symbols"][n.get(XML_ID)]: n for n in root.iter(f"{{{NS['mei']}}}note")}
    assert "accid" not in notes["n1"].attrib and notes["n1"].get("accid.ges") == "f"
    assert notes["n2"].get("accid") == "n"         # bécarre écrit
    assert "accid" not in notes["n3"].attrib        # bécarre encore en vigueur
    assert notes["n3"].get("tie") == "i"
    chord = root.find(".//mei:chord", NS)
    assert chord.get("dur") == "4" and len(chord.findall("mei:note", NS)) == 2
    tuplet = root.find(".//mei:tuplet", NS)
    assert (tuplet.get("num"), tuplet.get("numbase")) == ("3", "2")
    assert [n.get("dur") for n in tuplet.findall("mei:note", NS)] == ["8", "8", "8"]
    assert (notes["d"].get("dur"), notes["d"].get("dots")) == ("2", "1")


def test_multirest_changes_and_full_rest():
    root, _ = parse(sample())
    assert root.find(".//mei:multiRest", NS).get("num") == "8"
    changes = [s for s in root.findall(".//mei:section/mei:scoreDef", NS)]
    assert [(s.get("meter.count"), s.get("meter.unit")) for s in changes] == [("3", "4")]
    clef = root.find(".//mei:layer/mei:clef", NS)
    assert (clef.get("shape"), clef.get("line")) == ("F", "4")
    assert root.find(".//mei:mRest", NS) is not None


def test_empty_measure_and_octave_clef_and_two_staves():
    model = model_of([measure("m1", [], [treble("c", octave_change=-1), four_four()])])
    lower = [measure("b1", [note("b", "C", 3, "4")], [attribute("bc", "clef", sign="F", line=4)])]
    model.parts.append(Part(id="P2", measures=lower))
    model.parts.append(Part(id="P3", measures=[]))       # portée sans mesure : ignorée
    root, _ = parse(model)
    assert root.find(".//mei:mSpace", NS) is not None
    first, second = root.findall(".//mei:staffDef", NS)
    assert (first.get("clef.dis"), first.get("clef.dis.place")) == ("8", "below")
    assert second.get("clef.shape") == "F"
    assert root.find(".//mei:staffGrp", NS).get("symbol") == "brace"


def test_model_without_parts():
    root, result = parse(model_of([]))
    assert root.findall(".//mei:measure", NS) == [] and result["symbols"] == {}
