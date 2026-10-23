"""Appel d'Audiveris en ligne de commande.

Toutes les pages d'un morceau sont données à Audiveris en UN SEUL « livre » (un fichier
TIFF de plusieurs pages) : il garde ainsi le lien entre les pages (liaisons, chiffrage)
et Java ne démarre qu'une fois. Seules les pages où l'import a trouvé des portées sont
envoyées ; on garde la correspondance « feuille Audiveris n° → page d'origine n° ».

Audiveris produit dans le dossier de sortie :
- <nom>.omr        : son projet (symboles, positions, confiances), utile à la tâche 5 ;
- <nom>.mxl ou <nom>.mvt1.mxl, <nom>.mvt2.mxl... : la musique en MusicXML compressé.
  Il coupe en « mouvements » à chaque système en retrait ; le modèle interne les recolle ;
- <nom>-<date>.log : son journal.

Le journal affiché pendant le travail annonce chaque étape de chaque feuille,
par ex. « [livre#2] StepMonitoring 98 | HEADS » : on s'en sert pour la progression.
"""

import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from recomuse.importer import ImportedPage, preprocess
from recomuse.importer.loading import read_gray
from recomuse.recognition.tools import ocr_language_spec

# Étapes d'Audiveris pour chaque feuille, dans l'ordre (voir « Audiveris -help »).
AUDIVERIS_STEPS = (
    "LOAD", "BINARY", "SCALE", "GRID", "HEADERS", "STEM_SEEDS", "BEAMS", "LEDGERS",
    "HEADS", "STEMS", "REDUCTION", "CUE_BEAMS", "TEXTS", "MEASURES", "CHORDS", "CURVES",
    "SYMBOLS", "LINKS", "RHYTHMS", "PAGE",
)

# Temps maximal accordé par feuille, en secondes (une page dense prend environ 30 s).
SECONDS_PER_SHEET_LIMIT = 300

# Audiveris refuse les pages aux portées trop petites (« too low interline value »).
# Sous ce seuil (pixels à 300 dpi), la page est agrandie pour atteindre TARGET_INTERLINE.
MIN_INTERLINE = 15
TARGET_INTERLINE = 20
# Audiveris refuse aussi les images de plus de 20 millions de pixels (réglage
# LoadStep.maxPixelCount, qui protège la mémoire) : l'agrandissement est plafonné en
# conséquence, avec une petite marge. Une page A4 à 300 dpi peut ainsi grandir d'environ 1,5.
MAX_PIXELS = 20_000_000 * 0.98

# Nom du fichier image envoyé à Audiveris (et donc des fichiers qu'il produit).
BOOK_NAME = "livre"

# Ligne de progression du journal : « [livre#3] StepMonitoring 98 | HEADS ».
_STEP_LINE = re.compile(r"\[[^\]#]+#(?P<sheet>\d+)\]\s+StepMonitoring\s+\d+\s+\|\s+(?P<step>[A-Z_]+)")

# Numéro de mouvement dans un nom de fichier : « livre.mvt12.mxl » → 12.
_MOVEMENT_NUMBER = re.compile(r"\.mvt(\d+)\.mxl$")

# Fonction appelée pendant le travail : (étapes faites, étapes au total).
ProgressCallback = Callable[[int, int], None]


class AudiverisError(RuntimeError):
    """Audiveris n'a pas pu reconnaître la partition.

    `code` (traduit par l'interface) : « audiveris_failed », « audiveris_timeout »
    ou « no_music_recognized ».
    """

    def __init__(self, code: str, detail: str = "", log_path: Path | None = None) -> None:
        self.code = code
        self.detail = detail
        self.log_path = log_path
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass
class BookImage:
    """Fichier TIFF envoyé à Audiveris et correspondance feuilles → pages d'origine."""

    path: Path
    # sheet_pages[0] = numéro de page d'origine de la feuille 1, etc.
    sheet_pages: list[int]
    # Agrandissement appliqué à chaque feuille (1.0 = aucun). Pour retrouver la position
    # d'un symbole sur la page d'origine, diviser ses coordonnées par ce facteur.
    sheet_scales: list[float] = field(default_factory=list)


@dataclass
class AudiverisRun:
    """Résultat d'un passage d'Audiveris."""

    book: BookImage
    output_dir: Path
    omr_path: Path | None
    movement_paths: list[Path]          # fichiers MusicXML, dans l'ordre des mouvements
    log_path: Path | None
    duration_seconds: float
    console_lines: list[str] = field(default_factory=list)


def build_book_image(pages: list[ImportedPage], path: Path) -> BookImage:
    """Rassemble les pages qui contiennent des portées en un TIFF multipage.

    Les pages sans portée (couverture, instrumentation) et les pages blanches sont
    laissées de côté : Audiveris n'y trouverait rien, et elles lui coûteraient du temps.
    Les pages aux portées trop petites (conducteurs, certaines parties) sont agrandies.
    """
    selected = [p for p in pages if p.image_path is not None and p.interline is not None]
    if not selected:
        raise AudiverisError("no_music_recognized", "aucune page avec des portées")

    images = []
    scales = []
    for page in selected:
        pixels = read_gray(page.image_path)
        scale = sheet_scale(page.interline, pixels.shape[1], pixels.shape[0])
        images.append(preprocess.rescale(pixels, scale))
        scales.append(scale)

    # Compression LZW (code 5) : sans perte, et 3 à 4 fois plus petit.
    ok, encoded = cv2.imencodemulti(".tiff", images, [cv2.IMWRITE_TIFF_COMPRESSION, 5])
    if not ok:
        raise OSError(f"Impossible de créer {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.asarray(encoded).tofile(path)
    return BookImage(path=path, sheet_pages=[p.page_number for p in selected],
                     sheet_scales=scales)


def sheet_scale(interline: int, width: int, height: int) -> float:
    """Agrandissement à appliquer à une page pour qu'Audiveris accepte ses portées.

    Plafonné pour que l'image agrandie reste sous la taille maximale acceptée.
    """
    if interline >= MIN_INTERLINE:
        return 1.0
    largest = (MAX_PIXELS / (width * height)) ** 0.5
    return round(max(1.0, min(TARGET_INTERLINE / interline, largest)), 3)


def audiveris_command(audiveris: Path, book_path: Path, output_dir: Path,
                      tessdata: Path | None) -> list[str]:
    """Ligne de commande d'Audiveris : reconnaissance sans fenêtre et export MusicXML."""
    command = [
        str(audiveris),
        "-batch",          # sans interface graphique
        "-export",         # écrit le MusicXML
        "-swap",           # libère la mémoire de chaque feuille terminée (longs morceaux)
        "-output", str(output_dir),
    ]
    if tessdata:
        # Langues des textes : sinon Audiveris ne lit que l'anglais.
        language_option = ("org.audiveris.omr.text.Language.defaultSpecification="
                           + ocr_language_spec(tessdata))
        command += ["-constant", language_option]
    # « -- » sépare les options du fichier à traiter.
    command += ["--", str(book_path)]
    return command


def parse_progress_line(line: str) -> tuple[int, str] | None:
    """Extrait (n° de feuille, étape) d'une ligne du journal, ou None."""
    match = _STEP_LINE.search(line)
    if not match or match.group("step") not in AUDIVERIS_STEPS:
        return None
    return int(match.group("sheet")), match.group("step")


def steps_done(sheet: int, step: str) -> int:
    """Nombre d'étapes terminées quand la feuille `sheet` commence l'étape `step`."""
    return (sheet - 1) * len(AUDIVERIS_STEPS) + AUDIVERIS_STEPS.index(step)


def movement_files(output_dir: Path, book_name: str = BOOK_NAME) -> list[Path]:
    """Fichiers MusicXML produits, dans l'ordre des mouvements."""
    single = output_dir / f"{book_name}.mxl"
    if single.is_file():
        return [single]
    numbered = []
    for path in output_dir.glob(f"{book_name}.mvt*.mxl"):
        match = _MOVEMENT_NUMBER.search(path.name)
        if match:
            numbered.append((int(match.group(1)), path))
    return [path for _, path in sorted(numbered)]


def run_audiveris(audiveris: Path, book: BookImage, output_dir: Path,
                  tessdata: Path | None = None,
                  on_progress: ProgressCallback | None = None,
                  timeout_seconds: float | None = None) -> AudiverisRun:
    """Lance Audiveris sur un livre et attend la fin du travail."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # Résultats d'un passage précédent : à effacer, sinon un ancien « mvt5 » pourrait
    # se mêler aux nouveaux mouvements. (Uniquement nos propres fichiers de travail.)
    for old in [*output_dir.glob(f"{BOOK_NAME}*.mxl"), output_dir / f"{BOOK_NAME}.omr"]:
        old.unlink(missing_ok=True)
    total_steps = len(book.sheet_pages) * len(AUDIVERIS_STEPS)
    if timeout_seconds is None:
        timeout_seconds = SECONDS_PER_SHEET_LIMIT * len(book.sheet_pages)

    env = dict(os.environ)
    if tessdata:
        env["TESSDATA_PREFIX"] = str(tessdata)

    console_lines: list[str] = []
    start = time.perf_counter()
    process = subprocess.Popen(
        audiveris_command(audiveris, book.path, output_dir, tessdata),
        cwd=output_dir, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # Pas de fenêtre de console noire qui s'ouvre sous Windows.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    def read_console() -> None:
        # Lu dans un fil séparé : la lecture bloque, alors que l'attente doit
        # pouvoir s'interrompre au bout du temps maximal.
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            console_lines.append(line)
            progress = parse_progress_line(line)
            if progress and on_progress:
                on_progress(steps_done(*progress), total_steps)

    reader = threading.Thread(target=read_console, daemon=True)
    reader.start()
    try:
        exit_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise AudiverisError("audiveris_timeout", f"plus de {timeout_seconds:.0f} s") from None
    finally:
        reader.join(timeout=5)

    logs = sorted(output_dir.glob(f"{BOOK_NAME}-*.log"))
    log_path = logs[-1] if logs else None
    if exit_code != 0:
        raise AudiverisError("audiveris_failed", f"code de sortie {exit_code}", log_path)

    movements = movement_files(output_dir)
    if not movements:
        raise AudiverisError("no_music_recognized", "aucun MusicXML produit", log_path)

    if on_progress:
        on_progress(total_steps, total_steps)
    omr = output_dir / f"{BOOK_NAME}.omr"
    return AudiverisRun(
        book=book,
        output_dir=output_dir,
        omr_path=omr if omr.is_file() else None,
        movement_paths=movements,
        log_path=log_path,
        duration_seconds=round(time.perf_counter() - start, 1),
        console_lines=console_lines,
    )
