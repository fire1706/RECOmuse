"""Tests de la séparation des parties : portées vraiment imprimées sur une tranche de pages."""

from recomuse.model.score import Measure, Part
from recomuse.model.split import _printed_staves


def staff(ident: str, placed: bool) -> Part:
    return Part(id=ident, measures=[
        Measure(id=f"{ident}.m{k}", number=k, page=5,
                bbox=(0.0, 0.0, 10.0, 10.0) if placed else None) for k in (1, 2)])


def test_only_the_staves_printed_on_the_pages_are_kept():
    # 234 parties chez Audiveris, une seule imprimée sur ces pages : on ne garde qu'elle.
    printed, absent = staff("P234", True), staff("P1", False)
    staves = [(absent, absent.measures), (printed, printed.measures)]
    assert [p.id for p, _ in _printed_staves(staves)] == ["P234"]


def test_without_any_position_every_staff_is_kept():
    # Lecture sans positions (pas de .omr) : on garde tout, comme avant.
    absent = staff("P1", False)
    assert [p.id for p, _ in _printed_staves([(absent, absent.measures)])] == ["P1"]


def test_a_single_staff_part_spread_over_two_audiveris_parts_is_rejoined():
    from recomuse.model.score import PageInfo, ScoreModel
    from recomuse.model.split import _single_staff

    def measure(part, k, placed):
        return Measure(id=f"a0.{part}.{k}", number=k + 1, page=2,
                       bbox=(0.0, 0.0, 10.0, 10.0) if placed else None)

    # Le piccolo : systèmes 1 et 3 dans la partie 1, système 2 dans la partie 2 ; la partie
    # 2 n'existe que dans ce mouvement (elle a moins de mesures que la partie 1).
    first = Part(id="P1", measures=[measure(0, k, k != 1) for k in range(3)]
                 + [Measure(id="a1.0.0", number=4, page=3, bbox=(0.0, 0.0, 1.0, 1.0))])
    second = Part(id="P2", measures=[measure(1, k, k == 1) for k in range(3)])
    model = ScoreModel(parts=[first, second], pages=[PageInfo(2, None), PageInfo(3, None)])
    _, kept = _single_staff(model, 2, 3)
    assert [m.id for m in kept] == ["a0.0.0", "a0.1.1", "a0.0.2"]
    # Deux portées imprimées ensemble (conducteur, piano) : on ne réunit pas.
    second.measures[0].bbox = (0.0, 0.0, 10.0, 10.0)
    assert _single_staff(model, 2, 3) is None
