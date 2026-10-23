"""Tests de la séparation des parties d'un même PDF (model/split.py)."""

from recomuse.model.score import PageInfo, Part, ScoreModel
from recomuse.model.split import instrument_key, part_starts, split_parts
from recomuse.recognition.header import HeaderInfo

from validation_helpers import attribute, four_four, measure, note, treble

TITLE = "Throwin' Down"


def test_instrument_key():
    # L'en-tête courant reprend le titre ; « Drum Set » et « Drums » sont le même instrument.
    assert instrument_key("Guitar Throwin' Down", TITLE) == instrument_key("Guitar", TITLE)
    assert instrument_key("Drum Set") == instrument_key("Drums")
    assert instrument_key("Trumpet 1") != instrument_key("Trumpet 2")
    assert instrument_key("Trompette en Si♭ 2") == ("trompette", "en", "si", "2")
    assert instrument_key(None) is None
    assert instrument_key("Throwin' Down", TITLE) is None


def page_measures(page: int, count: int, first: bool, prefix: str = "m"):
    """`count` mesures d'une page ; la première page d'une partie commence par un chiffrage
    (le premier instrument seulement a aussi sa clé : la lecture ne répète pas ce qui ne
    change pas)."""
    result = []
    for k in range(count):
        attributes = [four_four(f"{prefix}{page}.{k}.t")] if first and k == 0 else []
        result.append(measure(f"{prefix}{page}.{k}", [note(f"{prefix}{page}.{k}.n", "C", 5, "4")],
                              attributes, page=page))
    return result


def grouped_model() -> tuple[ScoreModel, dict[int, HeaderInfo]]:
    """Trois pages : flûte (pages 1-2), puis clarinette (page 3)."""
    measures = page_measures(1, 3, True) + page_measures(2, 2, False) + page_measures(3, 4, True)
    measures[0].attributes.insert(0, treble("clef"))
    measures[0].attributes.insert(1, attribute("key", "key", fifths=-1))
    model = ScoreModel(title=TITLE, instrument="Flute",
                       parts=[Part(id="P1", measures=measures)],
                       pages=[PageInfo(n, None, 2000, 1200, "vector") for n in (1, 2, 3)])
    model.renumber()
    headers = {1: HeaderInfo(title=TITLE, instrument="Flute"),
               2: HeaderInfo(instrument=f"Flute {TITLE}"),          # en-tête courant
               3: HeaderInfo(title=TITLE, instrument="Clarinet")}
    return model, headers


def test_part_starts_at_each_new_instrument():
    model, headers = grouped_model()
    assert part_starts(model, headers) == [1, 3]


def test_same_instrument_starting_again_is_a_new_part():
    """Deux parties de même nom à la suite (deux exemplaires) : la page qui reprend le titre
    et s'ouvre sur un chiffrage sans numéro de mesure commence une partie."""
    model, headers = grouped_model()
    headers[3] = HeaderInfo(title=TITLE, instrument="Flute")
    assert part_starts(model, headers) == [1, 3]


def test_page_without_header_continues_the_part():
    model, headers = grouped_model()
    headers[3] = HeaderInfo()
    assert part_starts(model, headers) == [1]
    assert split_parts(model, headers) == [model]


def test_split_parts_keeps_pages_and_initial_state():
    model, headers = grouped_model()
    flute, clarinet = split_parts(model, headers)
    assert flute.instrument == "Flute" and clarinet.instrument == "Clarinet"
    assert [p.number for p in flute.pages] == [1, 2]
    assert [p.number for p in clarinet.pages] == [3]
    assert [m.number for m in clarinet.parts[0].measures] == [1, 2, 3, 4]
    assert clarinet.parts[0].name == "Clarinet"
    # La clarinette hérite de la clé et de l'armure : elles sont recopiées dans sa 1re mesure,
    # avant son propre chiffrage.
    first = clarinet.parts[0].measures[0]
    assert [s.kind for s in first.attributes] == ["clef", "key", "time"]
    assert first.attributes[1].value == {"fifths": -1}
    assert first.attributes[0].id == f"{first.id}.clef0"
    # Le modèle d'origine n'est pas modifié.
    assert [s.kind for s in model.parts[0].measures[5].attributes] == ["time"]


def test_every_staff_of_a_part_is_kept():
    """Piano (deux portées) : chaque tranche de pages garde ses deux portées."""
    model, headers = grouped_model()
    lower = page_measures(1, 3, True, "b") + page_measures(2, 2, False, "b")
    model.parts.append(Part(id="P2", measures=lower))
    flute, clarinet = split_parts(model, headers)
    assert len(flute.parts) == 2
    assert len(clarinet.parts) == 1
