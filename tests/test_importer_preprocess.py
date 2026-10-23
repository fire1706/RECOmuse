"""Tests du prétraitement : mesures des portées, redressement, mise à l'échelle."""

import cv2
import numpy as np
import pytest

from recomuse.importer import preprocess

from synthetic import rotate, staff_page


@pytest.fixture(scope="module")
def straight_page():
    return staff_page()


def test_staff_metrics_on_a_300_dpi_page(straight_page):
    metrics = preprocess.estimate_staff_metrics(straight_page)
    assert metrics is not None
    assert metrics.line_thickness == 3
    assert metrics.interline == 22


def test_staff_metrics_scale_with_resolution():
    metrics = preprocess.estimate_staff_metrics(staff_page(dpi=600))
    assert metrics.interline == 44


def test_no_staff_on_a_blank_page():
    assert preprocess.estimate_staff_metrics(np.full((500, 400), 255, np.uint8)) is None


@pytest.mark.parametrize("skew", [2.0, -1.3, 0.6, -4.5])
def test_skew_is_measured(straight_page, skew):
    # Pour redresser une page tournée de +2°, il faut la tourner de -2°.
    assert preprocess.estimate_skew(rotate(straight_page, skew)) == pytest.approx(-skew, abs=0.1)


def test_straight_page_is_not_rotated(straight_page):
    pixels, angle = preprocess.deskew(straight_page)
    assert angle == 0.0
    assert pixels is straight_page  # aucune copie floue inutile


def test_deskew_restores_staff_metrics(straight_page):
    pixels, angle = preprocess.deskew(rotate(straight_page, 2.5))
    assert angle == pytest.approx(-2.5, abs=0.1)
    assert pixels.shape == straight_page.shape
    # Coins découverts par la rotation : blancs (papier), pas noirs.
    assert pixels[0, 0] == 255
    metrics = preprocess.estimate_staff_metrics(pixels)
    assert metrics.interline == pytest.approx(22, abs=1)


def test_blank_page_skew_is_zero():
    assert preprocess.estimate_skew(np.full((800, 600), 255, np.uint8)) == 0.0


def test_rescale():
    image = np.full((100, 200), 255, np.uint8)
    assert preprocess.rescale(image, 2.0).shape == (200, 400)
    assert preprocess.rescale(image, 0.5).shape == (50, 100)
    assert preprocess.rescale(image, 1.0) is image


def test_dpi_estimated_from_interline():
    assert preprocess.estimate_dpi_from_interline(22) == pytest.approx(300)
    assert preprocess.estimate_dpi_from_interline(11) == pytest.approx(150)


def test_title_page_text_is_not_mistaken_for_staves():
    """Les grandes lettres d'une couverture ne doivent pas passer pour des portées."""
    cover = np.full((3508, 2480), 255, np.uint8)
    for row, text in enumerate(["Simon and", "Garfunkel", "Greatest Hits", "Band"]):
        cv2.putText(cover, text, (200, 600 + row * 400), cv2.FONT_HERSHEY_SCRIPT_COMPLEX,
                    6, 0, 18)
    assert preprocess.estimate_staff_metrics(cover) is None


def test_single_underline_is_not_a_staff():
    page = np.full((3508, 2480), 255, np.uint8)
    cv2.rectangle(page, (200, 500), (2200, 503), 0, -1)
    assert preprocess.estimate_staff_metrics(page) is None
