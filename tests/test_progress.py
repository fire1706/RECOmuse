"""Tests de la progression d'une lecture et de son annulation (progress.py)."""

import pytest

from recomuse.progress import ReadingCancelled, ReadingProgress


def test_fraction_follows_the_weighted_plan():
    progress = ReadingProgress()
    # 2 pages vectorielles (1 s chacune) et 1 feuille d'Audiveris (20 étapes de 1,5 s).
    progress.plan(vector=2, audiveris=20)
    progress.update("vector", 2, 2)
    assert progress.to_dict()["fraction"] == pytest.approx(2 / 32)
    progress.update("audiveris", 10, 20, page=1, pages=1)
    state = progress.to_dict()
    assert state["fraction"] == pytest.approx(17 / 32, abs=1e-3)
    assert (state["stage"], state["page"], state["pages"]) == ("audiveris", 1, 1)


def test_fraction_never_goes_back_and_never_reaches_one_before_the_end():
    progress = ReadingProgress()
    progress.plan(audiveris=20)
    progress.update("audiveris", 15, 20)
    before = progress.to_dict()["fraction"]
    # Audiveris relancé (page qui l'a fait planter) : ses étapes repartent de zéro.
    progress.update("audiveris", 0, 20)
    assert progress.to_dict()["fraction"] == before
    progress.update("audiveris", 20, 20)
    assert progress.to_dict()["fraction"] == 0.99
    progress.finish()
    assert progress.to_dict() | {"elapsed": 0} == {
        "stage": "done", "page": None, "pages": None, "fraction": 1.0, "elapsed": 0,
        "cancelling": False}


def test_smaller_plan_moves_the_bar_forward():
    progress = ReadingProgress()
    # Au pire, 4 pages scannées ; finalement toutes vectorielles.
    progress.plan(audiveris=80, vector=4)
    progress.update("vector", 2, 4)
    worst = progress.to_dict()["fraction"]
    progress.plan(audiveris=0)
    assert progress.to_dict()["fraction"] > worst


def test_cancel_stops_at_the_next_checkpoint():
    progress = ReadingProgress()
    progress.plan(vector=3)
    progress.update("vector", 1, 3)
    progress.cancel()
    assert progress.cancelled and progress.to_dict()["cancelling"]
    with pytest.raises(ReadingCancelled) as info:
        progress.update("vector", 2, 3)
    assert info.value.code == "cancelled"
    with pytest.raises(ReadingCancelled):
        progress.check()
