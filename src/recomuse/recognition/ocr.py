"""Lecture des textes d'une page avec Tesseract (programme externe).

On n'envoie à Tesseract que l'EN-TÊTE de la page : la zone au-dessus de la première
portée, où se trouvent le titre, le nom de l'instrument, le compositeur et le tempo.
Sur le reste de la page, Tesseract prendrait les notes pour des lettres.

Tesseract renvoie un tableau (format TSV) : un mot par ligne, avec sa position, sa
taille et sa confiance (0 à 100). On regroupe les mots en lignes de texte.
"""

import csv
import io
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from recomuse.importer import preprocess
from recomuse.importer.loading import read_gray, write_png
from recomuse.recognition.tools import ocr_language_spec

# Mode de découpage de Tesseract : 11 = « texte épars », sans ordre de lecture imposé.
# C'est celui qui sépare le mieux titre, instrument et compositeur posés çà et là.
PAGE_SEGMENTATION_MODE = "11"

# Mots dont la confiance est inférieure à ce seuil (sur 100) sont ignorés.
MIN_WORD_CONFIDENCE = 40

# Une rangée de pixels fait partie d'une portée si ses longs traits horizontaux
# couvrent au moins cette part de la largeur de la page.
STAFF_ROW_COVERAGE = 0.3

# Recherche du bas de l'en-tête, en interlignes au-dessus de la première portée : on coupe
# dans la rangée la moins encrée de cette bande, c'est-à-dire dans le blanc entre le texte
# (souvent le tempo, écrit juste au-dessus) et les notes ou la portée. Une marge fixe
# coupait le bas des lettres (« Allegro » lu « Allearo ») ou attrapait des bouts de notes.
HEADER_SEARCH_INTERLINES = (0.5, 3.5)

# Un nombre (numéro de mesure, pause multiple) n'est retenu que s'il est lu avec au moins
# cette confiance : une erreur de lecture décalerait toute la numérotation.
MIN_NUMBER_CONFIDENCE = 70

# Temps maximal accordé à Tesseract pour un en-tête, en secondes.
TESSERACT_TIMEOUT_SECONDS = 60


class OcrError(RuntimeError):
    """Tesseract a échoué (code « ocr_failed », traduit par l'interface)."""

    code = "ocr_failed"


@dataclass(frozen=True)
class OcrLine:
    """Une ligne de texte lue, avec sa boîte en pixels sur la page."""

    text: str
    left: int
    top: int
    width: int
    height: int          # hauteur des lettres : un titre est plus grand qu'un nom d'auteur
    confidence: float    # moyenne des confiances des mots (0 à 100)

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2


def header_bottom(gray: np.ndarray, interline: int | None) -> int:
    """Ordonnée (en pixels) du bas de l'en-tête, juste au-dessus de la première portée.

    S'il n'y a aucune portée, tout le quart supérieur de la page est pris comme en-tête.
    """
    lines = preprocess.long_horizontal_lines(gray)
    staff_rows = np.nonzero(lines.sum(axis=1) > STAFF_ROW_COVERAGE * gray.shape[1])[0]
    if staff_rows.size == 0:
        return gray.shape[0] // 4

    interline = interline or 20
    nearest, farthest = HEADER_SEARCH_INTERLINES
    low = max(0, int(staff_rows[0] - nearest * interline))    # bas de la bande de recherche
    high = max(0, int(staff_rows[0] - farthest * interline))  # haut de la bande
    if low <= high:
        return low
    ink_per_row = preprocess.binarize(gray[high:low]).sum(axis=1)
    # Parmi les rangées les moins encrées, la plus basse : on garde le plus de texte possible.
    emptiest = np.nonzero(ink_per_row == ink_per_row.min())[0]
    return high + int(emptiest[-1])


def tesseract_command(tesseract: Path, image: Path, tessdata: Path) -> list[str]:
    """Ligne de commande de Tesseract (résultat en TSV sur la sortie standard)."""
    return [
        str(tesseract), str(image), "stdout",
        "--tessdata-dir", str(tessdata),
        "-l", ocr_language_spec(tessdata),
        "--psm", PAGE_SEGMENTATION_MODE,
        "--dpi", "300",
        # Sortie TSV. (Le raccourci « tsv » en fin de commande ne marche pas ici : c'est un
        # fichier de réglages rangé dans le tessdata de Tesseract, pas dans le nôtre.)
        "-c", "tessedit_create_tsv=1",
    ]


def parse_tsv(tsv: str, offset_y: int = 0) -> list[OcrLine]:
    """Regroupe les mots du TSV de Tesseract en lignes de texte.

    offset_y : décalage vertical à ajouter (si l'image lue était un morceau de page).
    """
    words_by_line: dict[tuple[str, str, str], list[dict]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        # Niveau 5 = un mot (les niveaux 1 à 4 sont la page, les blocs, les paragraphes...).
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text or float(row["conf"]) < MIN_WORD_CONFIDENCE:
            continue
        key = (row["block_num"], row["par_num"], row["line_num"])
        words_by_line.setdefault(key, []).append(row)

    lines = []
    for words in words_by_line.values():
        lefts = [int(w["left"]) for w in words]
        tops = [int(w["top"]) for w in words]
        rights = [int(w["left"]) + int(w["width"]) for w in words]
        bottoms = [int(w["top"]) + int(w["height"]) for w in words]
        lines.append(OcrLine(
            text=" ".join(w["text"].strip() for w in words),
            left=min(lefts),
            top=min(tops) + offset_y,
            width=max(rights) - min(lefts),
            height=max(bottoms) - min(tops),
            confidence=round(sum(float(w["conf"]) for w in words) / len(words), 1),
        ))
    return sorted(lines, key=lambda line: (line.top, line.left))


def read_header(tesseract: Path, tessdata: Path, page_image: Path, interline: int | None,
                work_dir: Path) -> list[OcrLine]:
    """Lit les lignes de texte de l'en-tête d'une page (image PNG à 300 dpi)."""
    gray = read_gray(page_image)
    bottom = header_bottom(gray, interline)
    if bottom < 20:
        return []  # la première portée est collée au haut de la page : pas d'en-tête

    header_path = work_dir / f"{page_image.stem}-header.png"
    write_png(header_path, gray[:bottom])
    try:
        result = subprocess.run(
            tesseract_command(tesseract, header_path, tessdata),
            check=False, capture_output=True, timeout=TESSERACT_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError("délai dépassé") from exc
    if result.returncode != 0:
        raise OcrError(result.stderr.decode("utf-8", errors="replace").strip())
    return parse_tsv(result.stdout.decode("utf-8", errors="replace"))



def number_command(tesseract: Path, image: Path, tessdata: Path) -> list[str]:
    """Ligne de commande de Tesseract pour lire UN nombre (numéro de mesure, pause multiple)."""
    return [
        str(tesseract), str(image), "stdout",
        "--tessdata-dir", str(tessdata),
        "-l", "eng",
        "--psm", "8",                                  # un seul « mot » (le nombre)
        "-c", "tessedit_char_whitelist=0123456789",    # chiffres seulement
        "-c", "tessedit_create_tsv=1",                 # avec la confiance de chaque mot
    ]


def read_number(tesseract: Path, tessdata: Path, pixels: np.ndarray, work_path: Path) -> int | None:
    """Lit un nombre dans un petit morceau d'image (None si rien de lisible)."""
    if pixels.size == 0:
        return None
    write_png(work_path, pixels)
    try:
        result = subprocess.run(
            number_command(tesseract, work_path, tessdata),
            check=False, capture_output=True, timeout=TESSERACT_TIMEOUT_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return None
    lines = parse_tsv(result.stdout.decode("utf-8", errors="replace"))
    lines = [line for line in lines if line.confidence >= MIN_NUMBER_CONFIDENCE]
    digits = "".join(c for line in lines for c in line.text if c.isdigit())
    return int(digits) if digits and len(digits) <= 4 else None
