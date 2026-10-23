"""Reconnaissance complète d'une partition importée.

Enchaînement :
1. lecture vectorielle des pages vectorielles d'un PDF (tâche 4b) : structure et hauteurs
   exactes, qui serviront à contrôler Audiveris ;
2. lecture de l'en-tête de la première page de musique : texte exact du PDF si la page
   est vectorielle, sinon Tesseract (titre, instrument...) ;
3. passage d'Audiveris sur toutes les pages de musique (un seul livre). Les pages
   vectorielles y passent aussi tant que leurs durées ne sont pas lues (tâche 4b-2) ;
4. résumé des fichiers MusicXML produits, et textes d'Audiveris en secours.

Le résultat brut d'Audiveris (MusicXML, projet .omr) sera transformé en modèle interne
à la tâche 5, puis vérifié par le validateur (tâche 6).
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from recomuse.importer import ImportedScore
from recomuse.recognition import tools
from recomuse.recognition.audiveris import (
    BOOK_NAME,
    AudiverisRun,
    ProgressCallback,
    build_book_image,
    run_audiveris,
)
from recomuse.recognition.header import (
    HeaderInfo,
    analyze_header,
    complete_with_credits,
    lines_from_pdf_text,
)
from recomuse.recognition.musicxml import MovementSummary, summarize_movement
from recomuse.recognition.ocr import OcrError, OcrLine, read_header
from recomuse.vector import VectorScore, read_vector_pdf

# Avertissements (codes traduits par l'interface).
RecognitionWarning = Literal[
    "ocr_unavailable",           # Tesseract absent : en-tête non lu par RECOmuse
    "ocr_languages_missing",     # langues absentes : textes mal lus, voire pas du tout
    "ocr_failed",                # Tesseract a échoué sur l'en-tête
]

# Sous-dossier des résultats d'Audiveris dans le dossier de travail de la partition.
AUDIVERIS_DIRNAME = "audiveris"


@dataclass
class RecognitionResult:
    """Résultat de la reconnaissance d'une partition."""

    run: AudiverisRun
    movements: list[MovementSummary]
    header: HeaderInfo
    header_lines: list[OcrLine] = field(default_factory=list)
    warnings: list[RecognitionWarning] = field(default_factory=list)
    vector: VectorScore | None = None      # lecture directe des pages vectorielles

    @property
    def measure_count(self) -> int:
        return sum(m.measure_count for m in self.movements)

    def movement_pages(self, movement: MovementSummary) -> list[int]:
        """Numéros des pages d'origine (et non des feuilles du livre) d'un mouvement."""
        return [self.run.book.sheet_pages[sheet - 1] for sheet in sorted(movement.sheet_systems)]

    def to_dict(self) -> dict:
        """Version simple (textes, nombres, listes) pour l'interface ou un fichier JSON."""
        return {
            "sheet_pages": self.run.book.sheet_pages,
            "omr_path": str(self.run.omr_path) if self.run.omr_path else None,
            "log_path": str(self.run.log_path) if self.run.log_path else None,
            "duration_seconds": self.run.duration_seconds,
            "measure_count": self.measure_count,
            "movements": [
                {**asdict(m), "path": str(m.path), "pages": self.movement_pages(m)}
                for m in self.movements
            ],
            "header": asdict(self.header),
            "warnings": list(self.warnings),
            "vector": self.vector.to_dict() if self.vector else None,
        }


def recognize_score(score: ImportedScore, on_progress: ProgressCallback | None = None,
                    output_dir: Path | None = None) -> RecognitionResult:
    """Reconnaît la musique et les textes d'une partition importée (tâche 3).

    Lève ToolNotFoundError si Audiveris est absent, AudiverisError s'il échoue.
    """
    status = tools.check_tools()
    audiveris = tools.require(status.audiveris, "audiveris_not_found")
    output_dir = output_dir or score.work_dir / AUDIVERIS_DIRNAME
    warnings: list[RecognitionWarning] = []
    if status.missing_languages:
        warnings.append("ocr_languages_missing")

    # Le livre est construit en premier : s'il n'y a aucune page de musique, inutile
    # de lire l'en-tête.
    book = build_book_image(score.pages, output_dir / f"{BOOK_NAME}.tif")

    # 1. Lecture vectorielle (rapide : moins d'une seconde par page).
    vector = None
    vector_pages = [p.page_number for p in score.pages if p.kind == "vector"]
    if vector_pages and score.source_path.suffix.lower() == ".pdf":
        vector = read_vector_pdf(score.source_path, vector_pages)

    # 2. En-tête de la première page de musique : texte exact du PDF si possible.
    first_music_page = next(p for p in score.pages if p.page_number == book.sheet_pages[0])
    header_lines: list[OcrLine] = []
    header = HeaderInfo()
    vector_page = next((p for p in vector.pages if p.page_number == first_music_page.page_number),
                       None) if vector else None
    if vector_page is not None:
        header_lines = lines_from_pdf_text(vector_page.header_lines)
        header = analyze_header(header_lines, first_music_page.width)
    elif status.tesseract and status.tessdata:
        try:
            header_lines = read_header(status.tesseract, status.tessdata,
                                       first_music_page.image_path,
                                       first_music_page.interline, output_dir)
            header = analyze_header(header_lines, first_music_page.width)
        except OcrError:
            warnings.append("ocr_failed")
    else:
        warnings.append("ocr_unavailable")

    # 3. Audiveris.
    run = run_audiveris(audiveris, book, output_dir, status.tessdata, on_progress)

    # 4. Résumé de la musique, et textes d'Audiveris pour compléter l'en-tête.
    movements = [summarize_movement(path) for path in run.movement_paths]
    if movements:
        header = complete_with_credits(header, movements[0].credits)

    return RecognitionResult(run=run, movements=movements, header=header,
                             header_lines=header_lines, warnings=warnings, vector=vector)
