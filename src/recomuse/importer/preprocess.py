"""Prétraitement des pages scannées : redressement, mise à 300 dpi, mesure des portées.

Deux mesures de base en reconnaissance de partitions :
- l'ÉPAISSEUR des lignes de portée (en pixels) ;
- l'INTERLIGNE : distance entre deux lignes de portée consécutives (en pixels).
Elles s'obtiennent en parcourant l'image colonne par colonne : dans une colonne qui
traverse une portée, on rencontre une alternance régulière « trait noir / espace blanc ».
Les longueurs les plus fréquentes donnent l'épaisseur (noir) et l'espace (blanc).
Avant de mesurer, on ne garde que les longs traits horizontaux : sans cela, les
lettres d'une page de titre ressembleraient elles aussi à des portées.
La page doit donc être redressée AVANT d'être mesurée.

Le redressement cherche l'angle qui rend les lignes de portée parfaitement
horizontales : à ce moment-là, le noir se concentre sur quelques rangées de pixels.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from recomuse.importer.loading import TARGET_DPI

# Plage d'angles explorée pour le redressement, en degrés.
MAX_SKEW_DEGREES = 5.0

# En dessous de cet angle, on ne tourne pas l'image (la rotation la rendrait un peu floue
# pour un gain invisible).
MIN_ROTATION_DEGREES = 0.05

# Largeur de l'image réduite utilisée pour chercher l'angle (plus rapide).
SKEW_SEARCH_WIDTH = 1200

# Interligne typique d'une partie d'orchestre imprimée, scannée à 300 dpi
# (portée de 7 à 8 mm de haut → interligne d'environ 1,85 mm ≈ 22 pixels).
# Sert seulement à deviner la résolution d'une image qui ne l'indique pas.
REFERENCE_INTERLINE_AT_300_DPI = 22.0

# Nombre minimal de traits noirs (et d'espaces) mesurés pour se fier aux mesures de portée.
MIN_RUNS_FOR_METRICS = 200

# Longueur minimale d'un trait de portée : largeur de la page divisée par ce nombre.
LINE_MIN_LENGTH_DIVISOR = 25


@dataclass(frozen=True)
class StaffMetrics:
    """Mesures des portées d'une page, en pixels."""

    line_thickness: int
    interline: int


def binarize(gray: np.ndarray) -> np.ndarray:
    """Sépare l'encre du papier : renvoie un masque où l'encre vaut True.

    Le seuil est choisi automatiquement (méthode d'Otsu).
    """
    _, inverted = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return inverted > 0


def _vertical_runs(ink: np.ndarray, column_step: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Longueurs des traits noirs verticaux et des espaces blancs ENTRE deux traits noirs.

    Pour aller plus vite, on n'examine qu'une colonne sur `column_step`.
    """
    columns = ink[:, ::column_step].T.astype(np.int8)  # une ligne du tableau = une colonne
    # Bordure blanche en haut et en bas pour que chaque trait ait un début et une fin.
    padded = np.pad(columns, ((0, 0), (1, 1)))
    changes = np.diff(padded, axis=1)
    start_col, start_row = np.nonzero(changes == 1)   # passage blanc → noir
    end_col, end_row = np.nonzero(changes == -1)      # passage noir → blanc
    black = end_row - start_row
    # Espace blanc entre la fin d'un trait et le début du suivant, dans la même colonne.
    same_column = start_col[1:] == end_col[:-1]
    white = (start_row[1:] - end_row[:-1])[same_column]
    return black, white


def _most_frequent(values: np.ndarray, max_value: int) -> int | None:
    """Valeur la plus fréquente parmi 1..max_value, ou None s'il n'y en a pas."""
    values = values[(values >= 1) & (values <= max_value)]
    if values.size == 0:
        return None
    return int(np.bincount(values).argmax())


def long_horizontal_lines(gray: np.ndarray) -> np.ndarray:
    """Masque des longs traits horizontaux (lignes de portée, mais pas les lettres ni les notes).

    « Ouverture » morphologique : on ne garde que l'encre qui forme un trait horizontal
    continu d'au moins 1/25 de la largeur de la page (environ 1 cm).
    """
    ink = binarize(gray).astype(np.uint8)
    length = max(15, gray.shape[1] // LINE_MIN_LENGTH_DIVISOR)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1))
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel) > 0


def estimate_staff_metrics(gray: np.ndarray) -> StaffMetrics | None:
    """Mesure l'épaisseur des lignes et l'interligne. None si aucune portée n'est trouvée."""
    black, white = _vertical_runs(long_horizontal_lines(gray))
    # Il faut des traits ET des espaces entre eux : un simple soulignement ne suffit pas.
    if black.size < MIN_RUNS_FOR_METRICS or white.size < MIN_RUNS_FOR_METRICS:
        return None

    # Bornes larges : de 72 dpi (images d'écran) à 1200 dpi.
    thickness = _most_frequent(black, max_value=40)
    space = _most_frequent(white, max_value=200)
    if thickness is None or space is None:
        return None
    # Il faut au moins 3 pixels d'espace pour parler de portée.
    if space < 3:
        return None
    return StaffMetrics(line_thickness=thickness, interline=thickness + space)


def _rotate(image: np.ndarray, angle_degrees: float, border: int,
            interpolation: int = cv2.INTER_LINEAR) -> np.ndarray:
    """Tourne l'image autour de son centre (angle positif = sens inverse des aiguilles
    d'une montre). Les coins découverts sont remplis avec la couleur `border`."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle_degrees, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=interpolation,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def _horizontality_score(ink: np.ndarray, angle: float) -> float:
    """Plus le noir est concentré sur peu de rangées, plus le score est élevé."""
    rows = _rotate(ink, angle, border=0).sum(axis=1, dtype=np.float64)
    return float(np.square(rows).sum())


def estimate_skew(gray: np.ndarray) -> float:
    """Angle (en degrés) dont il faut tourner l'image pour rendre les portées horizontales."""
    height, width = gray.shape
    scale = min(1.0, SKEW_SEARCH_WIDTH / width)
    small = cv2.resize(gray, (max(1, round(width * scale)), max(1, round(height * scale))),
                       interpolation=cv2.INTER_AREA)
    ink = binarize(small).astype(np.uint8)
    if ink.sum() == 0:
        return 0.0  # page blanche

    def best_angle(candidates: np.ndarray) -> float:
        scores = [_horizontality_score(ink, a) for a in candidates]
        return float(candidates[int(np.argmax(scores))])

    # Recherche grossière, puis fine autour du meilleur angle.
    coarse = best_angle(np.arange(-MAX_SKEW_DEGREES, MAX_SKEW_DEGREES + 1e-9, 0.25))
    fine = best_angle(np.arange(coarse - 0.25, coarse + 0.25 + 1e-9, 0.02))
    return round(fine, 2)


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Redresse la page. Renvoie (image redressée, angle appliqué en degrés)."""
    angle = estimate_skew(gray)
    if abs(angle) < MIN_ROTATION_DEGREES:
        return gray, 0.0
    return _rotate(gray, angle, border=255, interpolation=cv2.INTER_CUBIC), angle


def rescale(gray: np.ndarray, factor: float) -> np.ndarray:
    """Agrandit ou réduit l'image d'un facteur donné."""
    if abs(factor - 1.0) < 0.01:
        return gray
    # INTER_AREA réduit sans crénelage ; INTER_CUBIC agrandit en restant net.
    interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC
    height, width = gray.shape
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return cv2.resize(gray, size, interpolation=interpolation)


def clean_enlarged(gray: np.ndarray) -> np.ndarray:
    """Passe en noir et blanc pur une page agrandie depuis une basse résolution.

    Agrandir une petite image (capture d'écran, scan à 75 dpi...) laisse des bords gris
    et flous autour des lignes et des notes : Audiveris s'y perd (vu sur une partie de
    tuba à environ 70 dpi : 2 mesures justes sur 35, armure et chiffrage manqués). En noir
    et blanc pur (seuil d'Otsu), il en lit 31 sur 35, avec l'armure et le chiffrage.
    """
    _, black_white = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return black_white


def estimate_dpi_from_interline(interline: int) -> float:
    """Devine la résolution d'une image d'après la taille de ses portées."""
    return TARGET_DPI * interline / REFERENCE_INTERLINE_AT_300_DPI
