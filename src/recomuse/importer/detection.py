"""Détection du type de chaque page d'un PDF : vectorielle, scannée ou blanche.

- Page VECTORIELLE : produite par un logiciel de gravure (Finale, Sibelius, MuseScore...).
  Les symboles sont des caractères d'une police de musique et les lignes des traits :
  on pourra les lire directement, sans reconnaissance d'image (tâche 4b).
- Page SCANNÉE : une photo de la page, sous forme d'une grande image.
  Elle peut contenir en plus une couche de texte invisible (OCR fait par le scanner) :
  ce texte ne la rend pas vectorielle.
- Page BLANCHE : rien d'exploitable.

Le type est décidé page par page, car un même PDF peut mélanger les deux
(ex. couverture scannée suivie de parties gravées).
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

import pymupdf

PageKind = Literal["vector", "scanned", "blank"]

# Mêmes valeurs que la colonne scores.source_kind du schéma SQL.
SourceKind = Literal["vector_pdf", "scanned_pdf", "image"]

# Part minimale de la page couverte par des images pour la considérer comme scannée.
SCANNED_COVERAGE_THRESHOLD = 0.5

# Débuts de noms de polices de musique connues (comparaison sans tenir compte des
# majuscules). Une police « XxxText » de la même famille sert aux accords et aux
# indications : elle compte aussi, car elle n'apparaît que dans les partitions gravées.
MUSIC_FONT_PREFIXES = (
    "maestro",          # Finale
    "petrucci",         # Finale
    "engraver",         # Finale
    "jazz",             # Finale (Jazz, JazzText, JazzPerc, JazzCord)
    "broadwaycopyist",  # Finale
    "finale",           # Finale (Finale Maestro, Finale Jazz...)
    "opus",             # Sibelius
    "inkpen",           # Sibelius
    "reprise",          # Sibelius
    "helsinki",         # Sibelius
    "norfolk",          # Sibelius
    "bravura",          # Dorico, MuseScore
    "leland",           # MuseScore 4
    "emmentaler",       # MuseScore, LilyPond
    "mscore",           # MuseScore 2
    "musejazz",         # MuseScore
    "sonata",           # Adobe Sonata
    "november",
    "goldenage",
    "lassus",
    "sebastian",
    "gootville",
    "petaluma",         # Dorico
    "musescore",
)


@dataclass(frozen=True)
class PageAnalysis:
    """Ce qu'on a appris d'une page PDF sans l'afficher."""

    page_number: int                 # à partir de 1
    kind: PageKind
    image_coverage: float            # part de la page couverte par des images (0 à 1)
    source_dpi: float | None         # résolution de la plus grande image (pages scannées)
    drawing_count: int               # nombre de tracés vectoriels
    text_length: int                 # nombre de caractères de texte
    music_fonts: list[str] = field(default_factory=list)


def font_base_name(font_name: str) -> str:
    """Retire le préfixe de sous-ensemble ajouté par les PDF : « EDWLKR+Maestro » → « Maestro »."""
    return font_name.split("+", 1)[1] if "+" in font_name else font_name


def is_music_font(font_name: str) -> bool:
    """Indique si une police est une police de musique connue."""
    base = font_base_name(font_name).replace(" ", "").replace("-", "").lower()
    return base.startswith(MUSIC_FONT_PREFIXES)


def analyze_pdf_page(page: pymupdf.Page) -> PageAnalysis:
    """Examine le contenu d'une page et décide de son type."""
    page_rect = page.rect
    page_area = abs(page_rect) or 1.0

    # Images posées sur la page : surface couverte et résolution.
    coverage = 0.0
    source_dpi = None
    largest_area = 0.0
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"]) & page_rect  # partie visible sur la page
        area = abs(bbox)
        coverage += area
        if area > largest_area and bbox.width > 0:
            largest_area = area
            # Largeur en pixels ÷ largeur en pouces (1 pouce = 72 points PDF).
            source_dpi = info["width"] / (bbox.width / 72)
    # Des images qui se chevauchent peuvent dépasser 100 % : on plafonne.
    coverage = min(coverage / page_area, 1.0)

    fonts = sorted({font_base_name(f[3]) for f in page.get_fonts() if is_music_font(f[3])})
    drawing_count = len(page.get_drawings())
    text_length = len(page.get_text().strip())

    if fonts:
        # Une police de musique ne trompe pas, même s'il y a une image de fond.
        kind: PageKind = "vector"
    elif coverage >= SCANNED_COVERAGE_THRESHOLD:
        kind = "scanned"
    elif drawing_count > 0 or text_length > 0:
        kind = "vector"
    elif coverage > 0:
        kind = "scanned"
    else:
        kind = "blank"

    return PageAnalysis(
        page_number=page.number + 1,
        kind=kind,
        image_coverage=round(coverage, 3),
        source_dpi=round(source_dpi, 1) if source_dpi else None,
        drawing_count=drawing_count,
        text_length=text_length,
        music_fonts=fonts,
    )


def document_kind(pages: list[PageAnalysis]) -> SourceKind:
    """Type global d'un PDF : celui de la majorité des pages non blanches.

    Ce type n'est qu'un résumé (pour la base et l'affichage) : les traitements
    suivants utilisent toujours le type de chaque page. En cas d'égalité, on
    retient « scanné », qui passe par la reconnaissance d'image et convient à tout.
    """
    counts = Counter(p.kind for p in pages if p.kind != "blank")
    return "vector_pdf" if counts["vector"] > counts["scanned"] else "scanned_pdf"
