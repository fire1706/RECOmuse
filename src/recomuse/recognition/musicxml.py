"""Lecture rapide des fichiers MusicXML produits par Audiveris.

Ce n'est PAS le modèle interne (tâche 5) : on n'en tire qu'un résumé, utile pour
vérifier la reconnaissance et pour récupérer les textes lus par Audiveris
(crédits en tête de page, indications de tempo, noms de parties).

Format .mxl : une archive ZIP contenant un fichier META-INF/container.xml qui
indique où se trouve la partition (« rootfile »).
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Nom du champ de provenance écrit par Audiveris : « source-sheet-3 » → feuille 3.
_SOURCE_SHEET = re.compile(r"source-sheet-(\d+)")


@dataclass(frozen=True)
class CreditText:
    """Texte placé librement sur la page (titre, compositeur, instrument...)."""

    text: str
    x: float | None          # position horizontale (dixièmes d'interligne, origine à gauche)
    y: float | None          # position verticale (origine EN BAS de la page)
    font_size: float | None


@dataclass
class MovementSummary:
    """Résumé d'un mouvement (fichier .mxl) reconnu par Audiveris."""

    path: Path
    # Systèmes du mouvement, par feuille du livre : {2: [8, 9, 10]} = systèmes 8 à 10
    # de la feuille 2. Un mouvement peut s'étendre sur plusieurs feuilles.
    sheet_systems: dict[int, list[int]]
    part_names: list[str]
    measure_count: int                 # mesures de la première partie
    time_signatures: list[str]         # ex. ["2/4", "3/4"], dans l'ordre d'apparition
    credits: list[CreditText] = field(default_factory=list)
    words: list[str] = field(default_factory=list)   # indications écrites (tempo, nuances...)


def read_root(mxl_path: Path) -> ET.Element:
    """Ouvre un .mxl et renvoie l'élément racine de la partition."""
    with zipfile.ZipFile(mxl_path) as archive:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfile = container.find(".//rootfile")
        if rootfile is None:
            raise ValueError(f"{mxl_path} : container.xml sans rootfile")
        return ET.fromstring(archive.read(rootfile.get("full-path")))


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def summarize_movement(mxl_path: Path) -> MovementSummary:
    """Lit un fichier .mxl d'Audiveris et en fait le résumé."""
    root = read_root(mxl_path)

    # Audiveris note la provenance du mouvement dans des champs « miscellaneous » :
    # name="source-sheet-2" et texte « 8 9 10 » = systèmes 8 à 10 de la feuille 2.
    sheet_systems: dict[int, list[int]] = {}
    for misc in root.iter("miscellaneous-field"):
        match = _SOURCE_SHEET.fullmatch(misc.get("name") or "")
        if match and misc.text:
            sheet_systems[int(match.group(1))] = [int(n) for n in misc.text.split()]

    first_part = root.find("part")
    time_signatures = [
        f"{t.findtext('beats')}/{t.findtext('beat-type')}"
        for t in (first_part.iter("time") if first_part is not None else [])
    ]

    credits = [
        CreditText(
            text=" ".join(w.text.split()),
            x=_float(w.get("default-x")),
            y=_float(w.get("default-y")),
            font_size=_float(w.get("font-size")),
        )
        for w in root.iter("credit-words") if w.text and w.text.strip()
    ]

    return MovementSummary(
        path=mxl_path,
        sheet_systems=sheet_systems,
        part_names=[(p.findtext("part-name") or "").strip() for p in root.iter("score-part")],
        measure_count=len(first_part.findall("measure")) if first_part is not None else 0,
        time_signatures=time_signatures,
        credits=credits,
        words=[" ".join(w.text.split()) for w in root.iter("words") if w.text and w.text.strip()],
    )
