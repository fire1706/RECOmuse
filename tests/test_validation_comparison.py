"""Tests de la comparaison entre les parties d'un même morceau (validation/comparison.py)."""

from recomuse.model.score import PageInfo, Part, ScoreModel
from recomuse.validation.comparison import (
    PartRef,
    align,
    compare_parts,
    group_by_title,
    part_refs,
    units,
)

from validation_helpers import attribute, measure, note, rest

# Une partie s'écrit en abrégé, une mesure par mot :
#   n = mesure de musique, r = mesure de silence, M8 = pause multiple de 8 mesures,
#   [A]n = mesure qui porte la lettre de répétition A, t3/4: = changement de chiffrage.
STRUCTURE = "t4/4:n n M8 [A]n n n t3/4:n n r [B]n n"


def make_part(spec: str, name: str = "P") -> Part:
    measures = []
    for k, word in enumerate(spec.split()):
        ident = f"{name}.{k}"
        attributes, events, marks = [], [], []
        if word.startswith("t"):
            time, word = word[1:].split(":")
            beats, beat_type = time.split("/")
            attributes.append(attribute(f"{ident}.t", "time", beats=int(beats),
                                        beat_type=int(beat_type)))
        if word.startswith("["):
            mark, word = word[1:].split("]")
            marks.append(mark)
        if word.startswith("M"):
            attributes.append(attribute(f"{ident}.mr", "multirest", count=int(word[1:])))
        elif word == "r":
            events.append(rest(f"{ident}.r", "4", full=True))
        elif word == "n":
            events.append(note(f"{ident}.n", "C", 5, "4"))
        measures.append(measure(ident, events, attributes, marks=marks))
    part = Part(id="P1", name=name, measures=measures)
    ScoreModel(parts=[part]).renumber()
    return part


def refs_of(*specs: str) -> list[PartRef]:
    return [PartRef(f"part{k}", make_part(spec, f"part{k}")) for k, spec in enumerate(specs)]


def test_units_unfold_multirests():
    seq = units(make_part(STRUCTURE))
    assert len(seq) == 18
    assert [u.time for u in seq if u.time] == ["4/4", "3/4"]
    assert [u.mark for u in seq if u.mark] == ["A", "B"]
    assert all(u.rest for u in seq[2:10])
    # Seule la 1re unité d'une pause multiple porte ses repères.
    assert [u.offset for u in seq[2:5]] == [0, 1, 2]


def test_align_identical_and_with_a_gap():
    a = units(make_part("n n [A]n n"))
    assert align(a, a) == [(0, 0), (1, 1), (2, 2), (3, 3)]
    b = units(make_part("n [A]n n"))
    pairs = align(b, a)
    assert (None, 1) in pairs or (None, 0) in pairs
    assert (1, 2) in pairs                      # les deux lettres A se correspondent


def test_identical_parts_have_no_issue():
    assert compare_parts(refs_of(STRUCTURE, STRUCTURE, STRUCTURE)).issues == []
    assert compare_parts(refs_of(STRUCTURE)).issues == []


def test_multirest_read_as_one_measure():
    """La pause de 8 mesures lue comme une seule mesure de silence : il manque 7 mesures,
    juste après ce silence ; proposition : en faire une pause multiple de 8."""
    bad = STRUCTURE.replace("M8", "r")
    report = compare_parts(refs_of(STRUCTURE, STRUCTURE, bad, STRUCTURE))
    [issue] = report.issues
    assert issue.code == "part_measures_missing"
    assert issue.part_id == "part2"
    assert issue.details["missing"] == 7
    assert issue.action == {"set_multirest": 8, "measure_id": "part2.2"}
    assert issue.measure_numbers == [3]
    assert issue.confidence >= 0.8


def test_multirest_count_misread():
    report = compare_parts(refs_of(STRUCTURE, STRUCTURE.replace("M8", "M6"), STRUCTURE))
    [issue] = report.issues
    assert issue.code == "part_measures_missing"
    assert [(f.symbol_id, f.value) for f in issue.fixes] == [("part1.2.mr", {"count": 8})]

    report = compare_parts(refs_of(STRUCTURE, STRUCTURE.replace("M8", "M11"), STRUCTURE))
    [issue] = report.issues
    assert issue.code == "part_measures_extra"
    assert issue.details["extra"] == 3
    assert [f.value for f in issue.fixes] == [{"count": 8}]


def test_extra_measure_without_explanation():
    """Une mesure en trop au milieu de la musique : signalée, sans correction proposée."""
    bad = STRUCTURE.replace("[A]n n n", "[A]n n n n")
    report = compare_parts(refs_of(STRUCTURE, bad, STRUCTURE))
    [issue] = report.issues
    assert issue.code == "part_measures_extra"
    assert issue.part_id == "part1"
    assert issue.fixes == [] and issue.action == {}


def test_reference_is_the_part_closest_to_the_others():
    """Une partie peut avoir la bonne longueur par hasard (une mesure en trop, une en moins
    plus loin) : elle ne doit pas servir de référence, c'est elle qui est signalée."""
    shifted = STRUCTURE.replace("[A]n n n", "[A]n n n n").replace("[B]n n", "[B]n")
    report = compare_parts(refs_of(shifted, STRUCTURE, STRUCTURE, STRUCTURE))
    assert {i.part_id for i in report.issues} == {"part0"}
    assert sorted(i.code for i in report.issues) == ["part_measures_extra",
                                                     "part_measures_missing"]


def test_time_signature_differs_from_the_other_parts():
    missed = STRUCTURE.replace("t3/4:n", "n")
    wrong = STRUCTURE.replace("t3/4:n", "t2/4:n")
    report = compare_parts(refs_of(STRUCTURE, missed, STRUCTURE, wrong, STRUCTURE))
    issues = {i.part_id: i for i in report.issues}
    assert set(issues) == {"part1", "part3"}
    assert issues["part1"].code == "part_time_signature_differs"
    assert issues["part1"].action == {"insert_time": "3/4", "before_measure": 14}
    assert [f.value for f in issues["part3"].fixes] == [{"beats": 3, "beat_type": 4}]
    assert issues["part3"].details["agreeing_parts"] == 3


def test_chord_names_are_not_rehearsal_marks():
    """Des accords (« E », « B7 ») lus comme des lettres dans une seule partie ne gênent
    pas l'alignement."""
    chords = STRUCTURE.replace("[A]n n n", "[A]n [E]n [B7]n")
    assert compare_parts(refs_of(STRUCTURE, chords, STRUCTURE)).issues == []


def model_with(name: str, title: str, *parts: Part, source: str = "vector") -> ScoreModel:
    return ScoreModel(title=title, instrument=name, parts=list(parts),
                      pages=[PageInfo(1, None, 2000, 1200, source)])


def test_part_refs_and_groups():
    piano = model_with("Piano", "Blues", make_part("n n", "Piano"), make_part("n", "Piano"))
    flute = model_with("Flute", "Blues", make_part("n n", "Flute"), source="audiveris")
    other = model_with("Flute", "Marche", make_part("n", "Flute"))
    refs = part_refs([piano, flute])
    # La main gauche du piano (même nom) n'est pas comparée à part.
    assert [(r.label, r.source) for r in refs] == [("Piano", "vector"), ("Flute", "audiveris")]
    groups = group_by_title([piano, flute, other])
    assert {title: len(models) for title, models in groups.items()} == {"blues": 2, "marche": 1}
