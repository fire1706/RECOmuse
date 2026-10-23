"""Lecture des pages sous forme d'images en niveaux de gris.

Une image est un tableau numpy de forme (hauteur, largeur), une valeur par pixel :
0 = noir, 255 = blanc.

Attention, sous Windows : cv2.imread et cv2.imwrite ne savent pas ouvrir un chemin
contenant des accents (« Partitions/Flûte.png »). On lit donc le fichier avec numpy
et on laisse OpenCV seulement décoder / encoder les octets.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf

# Résolution de travail : toutes les pages sont amenées à 300 dpi.
TARGET_DPI = 300

# Extensions d'images acceptées (en minuscules).
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

# Résolutions écrites par défaut par beaucoup de logiciels et d'appareils photo,
# sans rapport avec la taille réelle de la page : on ne s'y fie pas.
MEANINGLESS_DPI = {72, 96}


@dataclass
class LoadedImage:
    """Une page lue depuis un fichier image."""

    pixels: np.ndarray       # niveaux de gris, 8 bits
    dpi: float | None        # résolution indiquée dans le fichier, si elle est crédible


def render_pdf_page(page: pymupdf.Page, dpi: int = TARGET_DPI) -> np.ndarray:
    """Dessine une page PDF en niveaux de gris à la résolution demandée."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    # Copie : le tableau ne doit pas dépendre de la mémoire de PyMuPDF.
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def read_image_dpi(path: Path) -> float | None:
    """Résolution enregistrée dans un fichier image, ou None si absente ou peu crédible."""
    try:
        pix = pymupdf.Pixmap(str(path))
    except Exception:  # noqa: BLE001 - PyMuPDF lève des erreurs de types variés
        # Format que PyMuPDF ne sait pas lire : la résolution sera estimée autrement.
        return None
    dpi = float(pix.xres or 0)
    if dpi in MEANINGLESS_DPI or not 100 <= dpi <= 1200:
        return None
    return dpi


def _to_gray_uint8(image: np.ndarray) -> np.ndarray:
    """Convertit une image décodée par OpenCV en niveaux de gris 8 bits.

    Les parties transparentes (PNG) sont posées sur du blanc, comme sur du papier ;
    sans cela, elles deviendraient noires.
    """
    if image.dtype == np.uint16:
        image = (image / 257).astype(np.uint8)
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        color = image[:, :, :3].astype(np.float32)
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        image = (color * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def read_image_file(path: Path) -> list[LoadedImage]:
    """Lit un fichier image. Renvoie une page par image (un TIFF peut en contenir plusieurs).

    Lève ValueError si le contenu n'est pas une image lisible.
    """
    data = np.fromfile(path, dtype=np.uint8)
    dpi = read_image_dpi(path)

    if path.suffix.lower() in {".tif", ".tiff"}:
        ok, pages = cv2.imdecodemulti(data, cv2.IMREAD_UNCHANGED)
        if not ok or not pages:
            raise ValueError("image illisible")
        return [LoadedImage(_to_gray_uint8(p), dpi) for p in pages]

    raw = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError("image illisible")
    if raw.ndim == 3 and raw.shape[2] == 4:
        gray = _to_gray_uint8(raw)
    else:
        # IMREAD_GRAYSCALE applique l'orientation enregistrée par les appareils photo (EXIF).
        gray = _to_gray_uint8(cv2.imdecode(data, cv2.IMREAD_GRAYSCALE))
    return [LoadedImage(gray, dpi)]


def write_png(path: Path, pixels: np.ndarray) -> None:
    """Enregistre une image en PNG (sans perte), y compris dans un dossier avec accents."""
    ok, encoded = cv2.imencode(".png", pixels)
    if not ok:
        raise OSError(f"Impossible d'encoder l'image {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)
