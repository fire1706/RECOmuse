"""Lecture vectorielle d'un PDF entier et résumé par partie.

Une PARTIE est une portée d'un rang donné dans chaque système : dans une partie séparée,
il n'y a qu'une portée par système (rang 0) ; dans un conducteur, le rang 3 est la
4e portée de chaque système. Les mesures sont numérotées dans l'ordre de lecture,
à partir de 1, une pause multiple comptant pour autant de mesures qu'elle en annonce.
(La première mesure peut être une levée : le numéro imprimé, s'il existe, le dira.)
"""

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from recomuse.importer.detection import analyze_pdf_page
from recomuse.vector.reader import Measure, VectorPage, read_page


@dataclass(frozen=True)
class PartMeasure:
    """Une mesure d'une partie, avec son emplacement dans le PDF."""

    number: int          # numéro dans la partie (le premier d'une pause multiple)
    page: int            # numéro de page dans le PDF
    system: int          # rang du système dans la page (à partir de 0)
    measure: Measure


@dataclass
class VectorScore:
    """Ce que la lecture vectorielle a trouvé dans un PDF."""

    source_path: Path
    pages: list[VectorPage]
    warnings: list[str] = field(default_factory=list)

    @property
    def staff_count(self) -> int:
        """Nombre de portées par système (le plus grand rencontré)."""
        return max((len(system) for page in self.pages for system in page.systems), default=0)

    def part_measures(self, rank: int = 0) -> list[PartMeasure]:
        """Mesures de la partie de rang `rank`, dans l'ordre de lecture."""
        result = []
        number = 1
        for page in self.pages:
            for system_index, system in enumerate(page.systems):
                if rank >= len(system):
                    continue
                for measure in system[rank].measures:
                    result.append(PartMeasure(number, page.page_number, system_index, measure))
                    number += measure.length
        return result

    def measure_count(self, rank: int = 0) -> int:
        """Nombre total de mesures d'une partie (pauses multiples comprises)."""
        return sum(m.measure.length for m in self.part_measures(rank))

    def time_changes(self, rank: int = 0) -> list[tuple[int, str]]:
        """Changements d'indication de mesure : [(n° de mesure, « 3/4 »), ...]."""
        changes = []
        current = None
        for item in self.part_measures(rank):
            signature = item.measure.time_signature
            if signature and signature != current:
                changes.append((item.number, signature))
                current = signature
        return changes

    def key_changes(self, rank: int = 0) -> list[tuple[int, int]]:
        """Changements d'armure : [(n° de mesure, nombre de dièses (+) ou bémols (-))]."""
        changes = []
        current = None
        for item in self.part_measures(rank):
            fifths = item.measure.key_fifths
            if fifths is not None and fifths != current:
                changes.append((item.number, fifths))
                current = fifths
        return changes

    def multirests(self, rank: int = 0) -> list[tuple[int, int | None]]:
        """Pauses multiples : [(n° de la première mesure, nombre de mesures)]."""
        return [(m.number, m.measure.multirest) for m in self.part_measures(rank)
                if m.measure.is_multirest]

    def to_dict(self, rank: int = 0) -> dict:
        """Résumé simple (pour l'interface ou un fichier JSON)."""
        return {
            "pages": [p.page_number for p in self.pages],
            "staff_count": self.staff_count,
            "measure_count": self.measure_count(rank),
            "time_changes": self.time_changes(rank),
            "key_changes": self.key_changes(rank),
            "multirests": self.multirests(rank),
            "warnings": self.warnings,
        }


def read_vector_pdf(path: Path | str, page_numbers: list[int] | None = None) -> VectorScore:
    """Lit les pages vectorielles d'un PDF (toutes, ou celles de `page_numbers`, à partir de 1).

    Les pages scannées ou blanches sont ignorées : elles passent par Audiveris.
    """
    path = Path(path)
    pages = []
    warnings: set[str] = set()
    with pymupdf.open(path) as doc:
        numbers = page_numbers or range(1, doc.page_count + 1)
        for number in numbers:
            page = doc[number - 1]
            if analyze_pdf_page(page).kind != "vector":
                continue
            vector_page = read_page(page)
            warnings.update(vector_page.warnings)
            # Pages de texte seul (notice, instrumentation) : rien à garder.
            if vector_page.systems:
                pages.append(vector_page)
    return VectorScore(source_path=path, pages=pages, warnings=sorted(warnings))
