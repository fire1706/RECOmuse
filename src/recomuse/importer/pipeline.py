"""Import complet d'une partition : du fichier choisi par l'utilisateur aux pages prêtes
pour la reconnaissance.

Pour chaque page, on produit une image PNG en niveaux de gris à 300 dpi :
- page vectorielle : dessinée directement à 300 dpi (déjà droite et nette) ;
- page scannée     : dessinée à 300 dpi puis redressée ;
- fichier image    : redressé puis ramené à 300 dpi (résolution du fichier, ou estimée) ;
- page blanche     : ignorée (aucune image produite).

Le fichier d'origine n'est jamais modifié : il est seulement lu.
Les images produites vont dans un dossier de travail, hors du dépôt Git.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pymupdf

from recomuse.importer import preprocess
from recomuse.importer.detection import PageKind, SourceKind, analyze_pdf_page, document_kind
from recomuse.importer.errors import ScoreImportError
from recomuse.importer.loading import (
    IMAGE_EXTENSIONS,
    TARGET_DPI,
    read_image_file,
    render_pdf_page,
    write_png,
)

# En dessous de cette résolution d'origine, la reconnaissance risque d'être mauvaise.
LOW_RESOLUTION_DPI = 200

# Au-delà de cet angle, la page était nettement de travers : on le signale.
LARGE_SKEW_DEGREES = 3.0

# En dessous de cet interligne (pixels à 300 dpi), les portées sont très petites
# (conducteur, par ex.) et la reconnaissance devient difficile.
SMALL_STAFF_INTERLINE = 12

# Avertissements possibles sur une page (codes traduits par l'interface).
PageWarning = Literal[
    "small_staff",      # portées très petites (interligne sous 12 pixels à 300 dpi)
    "low_resolution",   # scan d'origine sous 200 dpi
    "dpi_estimated",    # résolution absente du fichier image, devinée d'après les portées
    "dpi_unknown",      # résolution absente et aucune portée pour la deviner
    "no_staff_found",   # aucune portée détectée sur une page qui devrait en contenir
    "large_skew",       # page fortement de travers
    "no_music_font",    # page vectorielle sans police de musique (texte seul ?)
]

# Fonction appelée après chaque page : (pages traitées, nombre total de pages).
ProgressCallback = Callable[[int, int], None]


@dataclass
class ImportedPage:
    """Une page prête pour la reconnaissance."""

    page_number: int                     # numéro dans le fichier d'origine, à partir de 1
    kind: PageKind
    image_path: Path | None              # PNG à 300 dpi (None pour une page blanche)
    width: int = 0
    height: int = 0
    source_dpi: float | None = None      # résolution d'origine (scans et images)
    rotation_degrees: float = 0.0        # angle appliqué pour redresser la page
    line_thickness: int | None = None    # épaisseur des lignes de portée, en pixels à 300 dpi
    interline: int | None = None         # interligne, en pixels à 300 dpi
    music_fonts: list[str] = field(default_factory=list)
    warnings: list[PageWarning] = field(default_factory=list)


@dataclass
class ImportedScore:
    """Résultat de l'import d'un fichier."""

    source_path: Path
    source_kind: SourceKind
    work_dir: Path
    pages: list[ImportedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def to_dict(self) -> dict:
        """Version simple (textes, nombres, listes) pour l'interface ou un fichier JSON."""
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        data["work_dir"] = str(self.work_dir)
        for page in data["pages"]:
            page["image_path"] = str(page["image_path"]) if page["image_path"] else None
        return data


def import_score(source: Path | str, work_dir: Path | str,
                 on_progress: ProgressCallback | None = None) -> ImportedScore:
    """Importe un PDF ou une image et prépare ses pages dans `work_dir`.

    Lève ScoreImportError si le fichier ne peut pas être importé.
    """
    source = Path(source)
    work_dir = Path(work_dir)

    if not source.is_file():
        raise ScoreImportError("file_not_found", source)

    suffix = source.suffix.lower()
    if suffix == ".pdf":
        source_kind, pages = _import_pdf(source, work_dir, on_progress)
    elif suffix in IMAGE_EXTENSIONS:
        source_kind, pages = "image", _import_image(source, work_dir, on_progress)
    else:
        raise ScoreImportError("unsupported_format", source, suffix)

    if all(page.kind == "blank" for page in pages):
        raise ScoreImportError("empty_document", source)

    return ImportedScore(source_path=source, source_kind=source_kind, work_dir=work_dir,
                         pages=pages)


def _page_image_path(work_dir: Path, page_number: int) -> Path:
    return work_dir / f"page-{page_number:03d}.png"


def _import_pdf(source: Path, work_dir: Path,
                on_progress: ProgressCallback | None) -> tuple[SourceKind, list[ImportedPage]]:
    try:
        doc = pymupdf.open(source)
    except Exception as exc:
        raise ScoreImportError("unreadable_file", source, str(exc)) from exc

    with doc:
        if doc.needs_pass:
            raise ScoreImportError("encrypted_pdf", source)
        if doc.page_count == 0:
            raise ScoreImportError("empty_document", source)

        analyses = []
        pages = []
        for page in doc:
            analysis = analyze_pdf_page(page)
            analyses.append(analysis)
            imported = ImportedPage(page_number=analysis.page_number, kind=analysis.kind,
                                    image_path=None, source_dpi=analysis.source_dpi,
                                    music_fonts=analysis.music_fonts)

            if analysis.kind != "blank":
                pixels = render_pdf_page(page, TARGET_DPI)
                if analysis.kind == "scanned":
                    pixels, imported.rotation_degrees = preprocess.deskew(pixels)
                    if analysis.source_dpi and analysis.source_dpi < LOW_RESOLUTION_DPI:
                        imported.warnings.append("low_resolution")
                elif not analysis.music_fonts:
                    imported.warnings.append("no_music_font")
                _finish_page(imported, pixels, work_dir)

            pages.append(imported)
            if on_progress:
                on_progress(len(pages), doc.page_count)

    return document_kind(analyses), pages


def _import_image(source: Path, work_dir: Path,
                  on_progress: ProgressCallback | None) -> list[ImportedPage]:
    try:
        images = read_image_file(source)
    except ValueError as exc:
        raise ScoreImportError("unreadable_file", source, str(exc)) from exc

    pages = []
    for index, image in enumerate(images, start=1):
        imported = ImportedPage(page_number=index, kind="scanned", image_path=None,
                                source_dpi=image.dpi)
        # Redressement d'abord : les portées ne se mesurent bien que sur une page droite.
        pixels, imported.rotation_degrees = preprocess.deskew(image.pixels)

        # Résolution d'origine : celle du fichier, sinon devinée d'après les portées.
        if imported.source_dpi is None:
            metrics = preprocess.estimate_staff_metrics(pixels)
            if metrics:
                imported.source_dpi = round(preprocess.estimate_dpi_from_interline(
                    metrics.interline), 1)
                imported.warnings.append("dpi_estimated")
            else:
                imported.warnings.append("dpi_unknown")

        if imported.source_dpi:
            pixels = preprocess.rescale(pixels, TARGET_DPI / imported.source_dpi)
            if (imported.source_dpi < LOW_RESOLUTION_DPI
                    and "dpi_estimated" not in imported.warnings):
                imported.warnings.append("low_resolution")

        _finish_page(imported, pixels, work_dir)
        pages.append(imported)
        if on_progress:
            on_progress(index, len(images))
    return pages


def _finish_page(page: ImportedPage, pixels: np.ndarray, work_dir: Path) -> None:
    """Mesure les portées, ajoute les avertissements et enregistre l'image de la page."""
    if abs(page.rotation_degrees) > LARGE_SKEW_DEGREES:
        page.warnings.append("large_skew")

    metrics = preprocess.estimate_staff_metrics(pixels)
    if metrics:
        page.line_thickness = metrics.line_thickness
        page.interline = metrics.interline
        if metrics.interline < SMALL_STAFF_INTERLINE:
            page.warnings.append("small_staff")
    elif "no_music_font" not in page.warnings:
        # Une page de texte seul a déjà son avertissement : inutile d'en ajouter un second.
        page.warnings.append("no_staff_found")

    page.height, page.width = pixels.shape
    page.image_path = _page_image_path(work_dir, page.page_number)
    write_png(page.image_path, pixels)


def register_score(conn: sqlite3.Connection, imported: ImportedScore,
                   title: str | None = None, part_name: str | None = None) -> int:
    """Enregistre la partition importée dans la base et renvoie son numéro."""
    with conn:
        cursor = conn.execute(
            "INSERT INTO scores (title, part_name, source_path, source_kind, page_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, part_name, str(imported.source_path), imported.source_kind,
             imported.page_count),
        )
    return cursor.lastrowid
