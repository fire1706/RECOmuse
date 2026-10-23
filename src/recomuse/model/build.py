"""Assemblage du modèle interne d'une partition à partir de ce qui a été reconnu.

Chaque page est lue par une seule source :
- page vectorielle lue avec succès → lecture vectorielle (exacte) ;
- autre page (scannée, ou police de musique illisible) → Audiveris.
Les mesures de chaque partie sont mises bout à bout dans l'ordre des pages, puis
numérotées (une pause multiple compte pour autant de mesures qu'elle en annonce).
"""

from recomuse.importer import ImportedScore
from recomuse.model import from_audiveris, from_vector
from recomuse.model.score import Measure, PageInfo, Part, ScoreModel
from recomuse.recognition.pipeline import RecognitionResult
from recomuse.vector import VectorScore


def vector_pages(vector: VectorScore | None) -> set[int]:
    """Pages lues avec succès par la lecture vectorielle."""
    return {p.page_number for p in vector.pages if p.systems} if vector else set()


def build_model(score: ImportedScore, recognition: RecognitionResult | None = None,
                vector: VectorScore | None = None) -> ScoreModel:
    """Construit le modèle d'une partition importée (tâche 3) et reconnue (tâches 4 et 4b)."""
    if vector is None and recognition is not None:
        vector = recognition.vector
    by_vector = vector_pages(vector)

    # Mesures de chaque partie, par source.
    parts: list[list[Measure]] = []
    if vector is not None and by_vector:
        for rank in range(vector.staff_count):
            parts.append(from_vector.build_part_measures(vector, rank))
    if recognition is not None and recognition.run is not None:
        for index, measures in enumerate(from_audiveris.build_parts(recognition)):
            kept = [m for m in measures if m.page not in by_vector]
            while len(parts) <= index:
                parts.append([])
            parts[index] += kept

    model = ScoreModel(source_path=str(score.source_path))
    for index, measures in enumerate(parts):
        # Ordre des pages ; l'ordre de lecture est conservé à l'intérieur d'une page.
        measures.sort(key=lambda m: m.page or 0)
        model.parts.append(Part(id=f"P{index + 1}", measures=measures))
    model.renumber()

    if recognition is not None:
        header = recognition.header
        model.title, model.instrument, model.tempo = header.title, header.instrument, header.tempo
        model.composers = list(header.composers)
    if len(model.parts) == 1:
        model.parts[0].name = model.instrument

    ran_audiveris = recognition is not None and recognition.run is not None
    by_audiveris = set(recognition.run.book.sheet_pages) if ran_audiveris else set()

    def source(number: int) -> str:
        if number in by_vector:
            return "vector"
        return "audiveris" if number in by_audiveris else "none"

    model.pages = [
        PageInfo(number=p.page_number,
                 image_path=str(p.image_path) if p.image_path else None,
                 width=p.width, height=p.height, source=source(p.page_number))
        for p in score.pages if p.image_path is not None
    ]
    return model
