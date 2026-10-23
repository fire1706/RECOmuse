"""Fabrication de fausses partitions pour les tests.

Aucune vraie partition ne peut être versionnée (droit d'auteur) : les tests dessinent
leurs propres pages — des portées, quelques têtes de notes et hampes — et les
enregistrent en PDF ou en image dans un dossier temporaire.
"""

from pathlib import Path

import cv2
import numpy as np
import pymupdf

# Format A4 en points PDF (1 point = 1/72 de pouce).
A4_WIDTH_PT, A4_HEIGHT_PT = 595, 842


def staff_page(dpi: int = 300, interline_at_300: int = 22, thickness_at_300: int = 3,
               systems: int = 9) -> np.ndarray:
    """Dessine une page A4 en niveaux de gris : portées de 5 lignes, notes et hampes."""
    scale = dpi / 300
    width, height = round(8.27 * dpi), round(11.69 * dpi)
    interline = round(interline_at_300 * scale)
    thickness = max(1, round(thickness_at_300 * scale))
    page = np.full((height, width), 255, dtype=np.uint8)

    margin = round(150 * scale)
    top = round(250 * scale)
    system_gap = (height - 2 * top) // systems
    rng = np.random.default_rng(0)  # toujours les mêmes « notes » : tests reproductibles
    for s in range(systems):
        y0 = top + s * system_gap
        for line in range(5):
            y = y0 + line * interline
            cv2.rectangle(page, (margin, y), (width - margin, y + thickness - 1), 0, -1)
        # Quelques notes : tête ovale + hampe.
        for x in range(margin + 3 * interline, width - margin - interline, 4 * interline):
            y = y0 + int(rng.integers(0, 9)) * interline // 2
            cv2.ellipse(page, (x, y), (round(interline * 0.65), round(interline * 0.45)),
                        -20, 0, 360, 0, -1)
            stem_x = x + round(interline * 0.55)
            cv2.line(page, (stem_x, y), (stem_x, y - round(3.5 * interline)), 0,
                     max(1, thickness - 1))
    return page


def rotate(image: np.ndarray, degrees: float) -> np.ndarray:
    """Met la page de travers (angle positif = sens inverse des aiguilles d'une montre)."""
    height, width = image.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                          borderValue=255)


def png_bytes(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def write_png_with_dpi(path: Path, image: np.ndarray, dpi: int | None) -> Path:
    """Enregistre une image PNG, avec ou sans résolution dans le fichier."""
    pix = pymupdf.Pixmap(png_bytes(image))
    if dpi:
        pix.set_dpi(dpi, dpi)
        pix.save(str(path))
    else:
        # OpenCV n'écrit aucune résolution.
        path.write_bytes(png_bytes(image))
    return path


def scanned_pdf(path: Path, pages: list[np.ndarray | None], ocr_text: str = "") -> Path:
    """PDF « scanné » : chaque page est une image pleine page.

    None donne une page blanche. ocr_text ajoute une couche de texte invisible,
    comme le font certains scanners.
    """
    doc = pymupdf.open()
    for image in pages:
        page = doc.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
        if image is not None:
            page.insert_image(page.rect, stream=png_bytes(image))
            if ocr_text:
                page.insert_text((50, 50), ocr_text, render_mode=3)  # 3 = invisible
    doc.save(str(path))
    doc.close()
    return path


def vector_pdf(path: Path, page_count: int = 1, with_title: bool = True) -> Path:
    """PDF « vectoriel » : portées tracées en traits, titre en texte."""
    doc = pymupdf.open()
    for _ in range(page_count):
        page = doc.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
        if with_title:
            page.insert_text((200, 60), "Marche de test", fontsize=18)
        interline_pt = 22 * 72 / 300  # 22 pixels à 300 dpi
        for s in range(9):
            y0 = 100 + s * 80
            for line in range(5):
                y = y0 + line * interline_pt
                page.draw_line((40, y), (A4_WIDTH_PT - 40, y), width=0.7)
    doc.save(str(path))
    doc.close()
    return path
