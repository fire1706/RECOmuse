"""Reconnaissance complète d'une partition importée.

Enchaînement :
1. lecture vectorielle des pages vectorielles d'un PDF (tâche 4b) : structure et hauteurs
   exactes, qui serviront à contrôler Audiveris ;
2. lecture de l'en-tête de la première page de musique : texte exact du PDF si la page
   est vectorielle, sinon Tesseract (titre, instrument...) ;
3. passage d'Audiveris sur les pages de musique que la lecture vectorielle n'a pas pu
   lire (un seul livre) : depuis la tâche 4b-2, une page vectorielle lue n'en a plus
   besoin. S'il ne reste aucune page, Audiveris n'est pas lancé (ni même nécessaire) ;
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
    AudiverisError,
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

    run: AudiverisRun | None               # None : toutes les pages ont été lues vectoriellement
    movements: list[MovementSummary]
    header: HeaderInfo
    header_lines: list[OcrLine] = field(default_factory=list)
    warnings: list[RecognitionWarning] = field(default_factory=list)
    vector: VectorScore | None = None      # lecture directe des pages vectorielles
    # En-tête de chaque page de musique (n° de page → titre, instrument...) : un PDF peut
    # contenir plusieurs parties à la suite (voir model/split.py).
    page_headers: dict[int, HeaderInfo] = field(default_factory=dict)

    @property
    def measure_count(self) -> int:
        return sum(m.measure_count for m in self.movements)

    def movement_pages(self, movement: MovementSummary) -> list[int]:
        """Numéros des pages d'origine (et non des feuilles du livre) d'un mouvement."""
        if self.run is None:
            return []
        return [self.run.book.sheet_pages[sheet - 1] for sheet in sorted(movement.sheet_systems)]

    def to_dict(self) -> dict:
        """Version simple (textes, nombres, listes) pour l'interface ou un fichier JSON."""
        run = self.run
        return {
            "sheet_pages": run.book.sheet_pages if run else [],
            "omr_path": str(run.omr_path) if run and run.omr_path else None,
            "log_path": str(run.log_path) if run and run.log_path else None,
            "duration_seconds": run.duration_seconds if run else 0.0,
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
                    output_dir: Path | None = None,
                    audiveris_for_vector_pages: bool = False) -> RecognitionResult:
    """Reconnaît la musique et les textes d'une partition importée (tâche 3).

    audiveris_for_vector_pages=True : envoie aussi à Audiveris les pages lues
    vectoriellement (pour comparer les deux lectures).
    Lève ToolNotFoundError si Audiveris est nécessaire mais absent, AudiverisError s'il
    échoue ou s'il n'y a aucune page de musique.
    """
    status = tools.check_tools()
    output_dir = output_dir or score.work_dir / AUDIVERIS_DIRNAME
    warnings: list[RecognitionWarning] = []
    if status.missing_languages:
        warnings.append("ocr_languages_missing")

    # Pages de musique : celles où l'import a trouvé des portées.
    music_pages = [p for p in score.pages if p.image_path is not None and p.interline is not None]
    if not music_pages:
        raise AudiverisError("no_music_recognized", "aucune page avec des portées")

    # 1. Lecture vectorielle (rapide : moins d'une seconde par page).
    vector = None
    pdf_vector_pages = [p.page_number for p in score.pages if p.kind == "vector"]
    if pdf_vector_pages and score.source_path.suffix.lower() == ".pdf":
        vector = read_vector_pdf(score.source_path, pdf_vector_pages)
    read_by_vector = {p.page_number for p in vector.pages if p.systems} if vector else set()

    # 2. En-tête de chaque page de musique : texte exact du PDF si possible, sinon Tesseract.
    page_headers: dict[int, HeaderInfo] = {}
    first_lines: list[OcrLine] = []
    for page in music_pages:
        lines = _page_header_lines(page, vector, status, output_dir, warnings)
        if lines is None:
            continue
        page_headers[page.page_number] = analyze_header(lines, page.width)
        if page is music_pages[0]:
            first_lines = lines
    header_lines = first_lines
    header = page_headers.get(music_pages[0].page_number, HeaderInfo())

    # 3. Audiveris, pour les pages que la lecture vectorielle n'a pas lues.
    for_audiveris = [p for p in music_pages
                     if audiveris_for_vector_pages or p.page_number not in read_by_vector]
    run = None
    movements: list[MovementSummary] = []
    if for_audiveris:
        audiveris = tools.require(status.audiveris, "audiveris_not_found")
        book = build_book_image(for_audiveris, output_dir / f"{BOOK_NAME}.tif")
        run = run_audiveris(audiveris, book, output_dir, status.tessdata, on_progress)
        # 4. Résumé de la musique, et textes d'Audiveris pour compléter l'en-tête.
        movements = [summarize_movement(path) for path in run.movement_paths]
        if movements:
            header = complete_with_credits(header, movements[0].credits)
    elif on_progress:
        on_progress(1, 1)

    return RecognitionResult(run=run, movements=movements, header=header,
                             header_lines=header_lines, warnings=warnings, vector=vector,
                             page_headers=page_headers)


def _page_header_lines(page, vector: VectorScore | None, status, output_dir: Path,
                       warnings: list) -> list[OcrLine] | None:
    """Lignes de l'en-tête d'une page : texte exact (page vectorielle) ou Tesseract.
    None si on ne peut pas les lire."""
    vector_page = next((p for p in vector.pages if p.page_number == page.page_number),
                       None) if vector else None
    if vector_page is not None:
        return lines_from_pdf_text(vector_page.header_lines)
    if not (status.tesseract and status.tessdata):
        if "ocr_unavailable" not in warnings:
            warnings.append("ocr_unavailable")
        return None
    try:
        return read_header(status.tesseract, status.tessdata, page.image_path, page.interline,
                           output_dir)
    except OcrError:
        if "ocr_failed" not in warnings:
            warnings.append("ocr_failed")
        return None
