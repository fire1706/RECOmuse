"""Image d'une question : la zone de la page concernée, les symboles douteux entourés.

L'image est renvoyée à l'interface sous forme de « data URL » (le PNG écrit en texte,
base64) : l'interface l'affiche directement, sans avoir à lire un fichier sur le disque.
"""

import base64
from pathlib import Path

import cv2
import numpy as np

from recomuse.importer.loading import read_gray

# Couleur du cadre autour d'un symbole douteux (orange vif, ordre des couleurs d'OpenCV :
# bleu, vert, rouge) et épaisseur du trait en pixels.
HIGHLIGHT_COLOR = (0, 120, 255)
HIGHLIGHT_THICKNESS = 3
# Marge entre le symbole et son cadre, en pixels.
HIGHLIGHT_PADDING = 6
# Largeur maximale de l'image envoyée (les extraits d'un système entier sont réduits).
MAX_WIDTH = 1200

Box = tuple[float, float, float, float]


def question_image(page: np.ndarray | Path, region: Box, highlights: list[Box],
                   max_width: int = MAX_WIDTH) -> str:
    """Découpe `region` (x, y, largeur, hauteur) dans l'image de la page, entoure les
    boîtes `highlights` et renvoie l'image en data URL PNG."""
    pixels = read_gray(page) if isinstance(page, Path) else page
    height, width = pixels.shape[:2]
    x, y, w, h = region
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(width, int(x + w)), min(height, int(y + h))
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Zone hors de la page : {region}")
    crop = cv2.cvtColor(pixels[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
    for bx, by, bw, bh in highlights:
        top_left = (int(bx) - x0 - HIGHLIGHT_PADDING, int(by) - y0 - HIGHLIGHT_PADDING)
        bottom_right = (int(bx + bw) - x0 + HIGHLIGHT_PADDING,
                        int(by + bh) - y0 + HIGHLIGHT_PADDING)
        cv2.rectangle(crop, top_left, bottom_right, HIGHLIGHT_COLOR, HIGHLIGHT_THICKNESS)
    if crop.shape[1] > max_width:
        scale = max_width / crop.shape[1]
        crop = cv2.resize(crop, (max_width, max(1, round(crop.shape[0] * scale))),
                          interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("Encodage PNG impossible.")
    return "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
