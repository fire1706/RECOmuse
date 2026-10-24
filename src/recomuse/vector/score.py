"""Lecture vectorielle d'un PDF entier et résumé par partie.

Une PARTIE est une portée d'un rang donné dans chaque système : dans une partie séparée,
il n'y a qu'une portée par système (rang 0) ; dans un conducteur, le rang 3 est la
4e portée de chaque système. Les mesures sont numérotées dans l'ordre de lecture,
à partir de 1, une pause multiple comptant pour autant de mesures qu'elle en annonce.
(La première mesure peut être une levée : le numéro imprimé, s'il existe, le dira.)

Dans un conducteur, le nom de chaque instrument est écrit à gauche de sa portée (en entier
au premier système, souvent abrégé ensuite) : staff_names() le retrouve pour chaque rang.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from recomuse.importer.detection import analyze_pdf_page
from recomuse.vector.primitives import TextLine
from recomuse.vector.reader import Measure, StaffContent, VectorPage, read_page

# Un nom d'instrument contient des lettres (un nombre seul est un numéro de mesure).
_HAS_LETTERS = re.compile(r"[A-Za-zÀ-ÿ]")


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

    def staff_names(self) -> list[str | None]:
        """Nom de l'instrument de chaque rang de portée (None s'il n'est pas écrit) : celui
        du premier système où il apparaît, d'ordinaire le nom complet."""
        names: list[str | None] = [None] * self.staff_count
        for page in self.pages:
            for system in page.systems:
                for rank, label in enumerate(system_labels(page.texts, system)):
                    if label and names[rank] is None:
                        names[rank] = label
        return names

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

    def duration_mismatches(self, rank: int = 0) -> list[int]:
        """Numéros des mesures dont la durée lue ne correspond pas au chiffrage.

        Une première mesure plus courte est une levée (anacrouse) : ce n'est pas une erreur.
        """
        wrong = []
        for item in self.part_measures(rank):
            measure = item.measure
            if measure.duration_ok is not False:
                continue
            if item.number == 1 and measure.duration < measure.expected_duration:
                continue   # levée
            wrong.append(item.number)
        return wrong

    def to_dict(self, rank: int = 0) -> dict:
        """Résumé simple (pour l'interface ou un fichier JSON)."""
        return {
            "pages": [p.page_number for p in self.pages],
            "staff_count": self.staff_count,
            "measure_count": self.measure_count(rank),
            "time_changes": self.time_changes(rank),
            "key_changes": self.key_changes(rank),
            "multirests": self.multirests(rank),
            "duration_mismatches": self.duration_mismatches(rank),
            "warnings": self.warnings,
        }


def read_vector_pdf(path: Path | str, page_numbers: list[int] | None = None,
                    on_page: Callable[[int, int], None] | None = None) -> VectorScore:
    """Lit les pages vectorielles d'un PDF (toutes, ou celles de `page_numbers`, à partir de 1).

    Les pages scannées ou blanches sont ignorées : elles passent par Audiveris.
    `on_page(faites, total)` est appelé après chaque page (barre de progression).
    """
    path = Path(path)
    pages = []
    warnings: set[str] = set()
    states: dict[int, dict] = {}   # clé, armure, chiffrage de chaque partie, de page en page
    with pymupdf.open(path) as doc:
        numbers = page_numbers or range(1, doc.page_count + 1)
        for index, number in enumerate(numbers):
            if on_page:
                on_page(index, len(numbers))
            page = doc[number - 1]
            if analyze_pdf_page(page).kind != "vector":
                continue
            vector_page = read_page(page, states)
            warnings.update(vector_page.warnings)
            # Pages de texte seul (notice, instrumentation) : rien à garder.
            if vector_page.systems:
                pages.append(vector_page)
    return VectorScore(source_path=path, pages=pages, warnings=sorted(warnings))


def system_labels(texts: list[TextLine], system: list[StaffContent]) -> list[str | None]:
    """Nom écrit à gauche de chaque portée d'un système. Un nom placé entre deux portées
    (accolade du piano) vaut pour les deux ; un nom sur deux lignes (« Trumpet » /
    « in B♭ 1 ») est réuni."""
    if not system:
        return []
    staves = [content.staff for content in system]
    left = min(staff.x0 for staff in staves)
    interline = min(staff.interline for staff in staves)
    found: list[list[TextLine]] = [[] for _ in staves]
    for text in texts:
        if text.x1 > left + interline or not _HAS_LETTERS.search(text.text):
            continue
        middle = (text.y0 + text.y1) / 2
        inside = [k for k, staff in enumerate(staves)
                  if staff.top - interline <= middle <= staff.bottom + interline]
        between = [k for k in range(len(staves) - 1)
                   if staves[k].bottom < middle < staves[k + 1].top]
        if inside:
            found[min(inside, key=lambda k: abs((staves[k].top + staves[k].bottom) / 2
                                                - middle))].append(text)
        elif between:
            found[between[0]].append(text)
            found[between[0] + 1].append(text)
    return [" ".join(t.text for t in sorted(group, key=lambda t: t.y0)) or None
            for group in found]
