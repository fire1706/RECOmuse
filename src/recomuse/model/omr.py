"""Lecture du projet d'Audiveris (.omr) : position et confiance de chaque symbole.

Le MusicXML d'Audiveris donne la musique mais pas la position des symboles sur la page,
ni leur note de confiance. Le projet .omr (archive ZIP) les contient : pour chaque feuille,
un fichier « sheet#N/sheet#N.xml » organisé ainsi :

    page → system → stack (une colonne de mesures : abscisses gauche et droite, en pixels)
                  → part → measure (dans l'ordre des stacks) : identifiants de ses
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
    # Hauteur des portées de la partie (haut de la 1re ligne, bas de la dernière), en pixels :
    # donne une boîte même à une mesure sans accord (pause multiple mal lue).
    staff_top: float | None = None
    staff_bottom: float | None = None
    attributes: list[OmrSymbol] = field(default_factory=list)   # clés, armures, chiffrages
    multirest_count: int | None = None


@dataclass
class OmrSheet:
    width: int
    height: int
    # systems[id du système] = mesures de chaque partie : systems["1"][0] = 1re partie
    systems: dict[str, list[list[OmrMeasure]]] = field(default_factory=dict)
    # part_ids[id du système] = numéro de partie logique de chacune de ses parties (le
    # « P234 » du MusicXML est la partie logique 234). Un système ne contient pas toujours
    # toutes les parties : dans un PDF de parties séparées, chaque page n'en a qu'une.
    part_ids: dict[str, list[int | None]] = field(default_factory=dict)


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

        # Colonnes de mesures du système, de gauche à droite. Les mesures d'une partie sont
        # dans le même ordre (leurs identifiants ne sont PAS ceux des colonnes).
        stacks = [(float(s.get("left")), float(s.get("right"))) for s in system.findall("stack")]
        # Tous les accords et silences du système. La liste « head-chords » d'une mesure
        # est incomplète (les accords ligaturés n'y sont pas) : on prend donc les accords
        # de la portée de la partie dont l'abscisse tombe dans la colonne de la mesure.
        all_chords = [OmrChord(symbol, [symbols[h] for h in contained.get(symbol.id, [])
                                        if h in symbols and symbols[h].kind == "head"])
                      for symbol in symbols.values() if symbol.kind in ("head-chord", "rest-chord")]
        parts = []
        ids: list[int | None] = []
        for part in system.findall("part"):
            ids.append(int(part.get("id")) if (part.get("id") or "").isdigit() else None)
            staff_ids = {int(s.get("id")) for s in part.findall("staff") if s.get("id")}
            line_ys = [float(point.get("y")) for staff in part.findall("staff")
                       for point in staff.iter("point") if point.get("y")]
            measures = []
            for index, element in enumerate(part.findall("measure")):
                left, right = stacks[index] if index < len(stacks) else (0.0, 0.0)
                measure = OmrMeasure(left=left, right=right,
                                     staff_top=min(line_ys) if line_ys else None,
                                     staff_bottom=max(line_ys) if line_ys else None)
                listed = set(_ids(element.find("head-chords")) + _ids(element.find("rest-chords")))
                for chord in all_chords:
                    center = chord.symbol.bounds[0] + chord.symbol.bounds[2] / 2
                    in_part = chord.symbol.staff in staff_ids if staff_ids else True
                    if chord.symbol.id in listed or (in_part and left <= center < right):
                        measure.chords.append(chord)
                for tag in ("clefs", "keys", "times"):
                    measure.attributes += [symbols[i] for i in _ids(element.find(tag))
                                           if i in symbols]
                # Barre de pause multiple de la colonne (elle n'est pas listée par la mesure).
                measure.attributes += [
                    s for s in symbols.values()
                    if s.kind == "multiple-rest" and (s.staff in staff_ids if staff_ids else True)
                    and left <= s.bounds[0] + s.bounds[2] / 2 < right]
                for symbol, value in counts:
                    if left <= symbol.bounds[0] <= right:
                        measure.multirest_count = value
                measures.append(measure)
            parts.append(measures)
        result.systems[system.get("id")] = parts
        result.part_ids[system.get("id")] = ids
    return result
