"""Extraits d'image : le morceau de la page autour d'un symbole.

Ils servent à poser une question (« quelle est cette note ? ») et sont gardés avec chaque
correction, pour que RECOmuse apprenne à reconnaître ce symbole. Ils sont découpés à la
demande, dans l'image de la page à 300 dpi préparée à l'import.
"""

from pathlib import Path

from recomuse.importer.loading import read_gray, write_png

# Marge autour du symbole, en pixels (à 300 dpi, 60 pixels ≈ 3 interlignes) : le musicien
# doit voir la portée et les voisins pour reconnaître le symbole.
SNIPPET_MARGIN = 60


def crop_snippet(page_image: Path, bbox: tuple[float, float, float, float], out_path: Path,
                 margin: int = SNIPPET_MARGIN) -> Path:
    """Découpe la zone `bbox` (x, y, largeur, hauteur) de la page, avec une marge, et
    l'enregistre en PNG. Renvoie le chemin de l'extrait."""
    pixels = read_gray(page_image)
    height, width = pixels.shape
    x, y, w, h = bbox
    x0 = max(0, int(x) - margin)
    y0 = max(0, int(y) - margin)
    x1 = min(width, int(x + w) + margin)
    y1 = min(height, int(y + h) + margin)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Boîte hors de la page : {bbox}")
    write_png(out_path, pixels[y0:y1, x0:x1])
    return out_path
