"""Lecture du projet d'Audiveris (.omr) : position et confiance de chaque symbole.

Le MusicXML d'Audiveris donne la musique mais pas la position des symboles sur la page,
ni leur note de confiance. Le projet .omr (archive ZIP) les contient : pour chaque feuille,
un fichier « sheet#N/sheet#N.xml » organisé ainsi :

    page → system → stack (une colonne de mesures : abscisses gauche et droite, en pixels)
                  → part → measure (même identifiant que sa stack) : identifiants de ses
                           accords (head-chords), silences (rest-chords), clés, armures...
                  → sig/inters : tous les symboles, chacun avec sa boîte (bounds) en pixels
                                 de la feuille et sa note (grade, ctx-grade de 0 à 1)
                  → sig relations : liens entre symboles (un accord « contient » ses têtes)

Les pixels sont ceux de l'image donnée à Audiveris : la page à 300 dpi, éventuellement
agrandie (voir recognition/audiveris.py, sheet_scales).
"""

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OmrSymbol:
    """Un symbole du projet Audiveris."""

    id: str
    kind: str                                   # head, rest, clef, key, time-pair...
    bounds: tuple[float, float, float, float]   # x, y, largeur, hauteur (pixels de la feuille)
    grade: float                                # confiance d'Audiveris (0 à 1)
    staff: int | None
    pitch: float | None                         # hauteur : 0 = ligne du milieu, + vers le bas


@dataclass
class OmrChord:
    """Un accord (ou un silence) et ses têtes."""

    symbol: OmrSymbol
    heads: list[OmrSymbol] = field(default_factory=list)   # vide pour un silence

    @property
    def is_rest(self) -> bool:
        return self.symbol.kind == "rest-chord"


@dataclass
class OmrMeasure:
    """Une mesure d'une partie dans un système."""

    left: float
    right: float
    chords: list[OmrChord] = field(default_factory=list)
    attributes: list[OmrSymbol] = field(default_factory=list)   # clés, armures, chiffrages
    multirest_count: int | None = None


@dataclass
class OmrSheet:
    width: int
    height: int
    # systems[id du système] = mesures de chaque partie : systems["1"][0] = 1re partie
    systems: dict[str, list[list[OmrMeasure]]] = field(default_factory=dict)


def _symbol(element: ET.Element) -> OmrSymbol | None:
    bounds = element.find("bounds")
    if bounds is None or element.get("id") is None:
        return None
    grade = element.get("ctx-grade") or element.get("grade") or "0.5"
    pitch = element.get("pitch")
    staff = element.get("staff")
    return OmrSymbol(
        id=element.get("id"), kind=element.tag,
        bounds=tuple(float(bounds.get(k)) for k in ("x", "y", "w", "h")),
        grade=float(grade), staff=int(staff) if staff else None,
        pitch=float(pitch) if pitch is not None else None,
    )


def _ids(element: ET.Element | None) -> list[str]:
    return (element.text or "").split() if element is not None else []


def read_sheet(omr_path: Path, sheet: int) -> OmrSheet | None:
    """Lit une feuille du projet .omr (None si elle est absente)."""
    name = f"sheet#{sheet}/sheet#{sheet}.xml"
    with zipfile.ZipFile(omr_path) as archive:
        if name not in archive.namelist():
            return None
        root = ET.fromstring(archive.read(name))

    picture = root.find("picture")
    result = OmrSheet(width=int(picture.get("width", 0)) if picture is not None else 0,
                      height=int(picture.get("height", 0)) if picture is not None else 0)

    for system in root.iter("system"):
        sig = system.find("sig")
        inters = sig.find("inters") if sig is not None else None
        symbols = {}
        if inters is not None:
            for element in inters:
                symbol = _symbol(element)
                if symbol is not None:
                    symbols[symbol.id] = symbol
        # Têtes contenues dans chaque accord.
        contained: dict[str, list[str]] = {}
        if sig is not None:
            for relation in sig.iter("relation"):
                if relation.find("containment") is not None:
                    contained.setdefault(relation.get("source"), []).append(relation.get("target"))
        # Nombre des pauses multiples (symbole « measure-count » au-dessus de la barre).
        counts = [(s, int(e.get("value"))) for e in (inters if inters is not None else [])
                  if e.tag == "measure-count" and e.get("value", "").isdigit()
                  for s in [symbols.get(e.get("id"))] if s is not None]

        stacks = {s.get("id"): (float(s.get("left")), float(s.get("right")))
                  for s in system.findall("stack")}
        parts = []
        for part in system.findall("part"):
            measures = []
            for element in part.findall("measure"):
                left, right = stacks.get(element.get("id"), (0.0, 0.0))
                measure = OmrMeasure(left=left, right=right)
                chord_ids = _ids(element.find("head-chords")) + _ids(element.find("rest-chords"))
                for chord_id in chord_ids:
                    chord = symbols.get(chord_id)
                    if chord is None:
                        continue
                    heads = [symbols[h] for h in contained.get(chord_id, [])
                             if h in symbols and symbols[h].kind == "head"]
                    measure.chords.append(OmrChord(chord, heads))
                for tag in ("clefs", "keys", "times"):
                    measure.attributes += [symbols[i] for i in _ids(element.find(tag))
                                           if i in symbols]
                for symbol, value in counts:
                    if left <= symbol.bounds[0] <= right:
                        measure.multirest_count = value
                measures.append(measure)
            parts.append(measures)
        result.systems[system.get("id")] = parts
    return result
