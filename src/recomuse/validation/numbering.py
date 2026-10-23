"""Pauses multiples et numéros de mesure imprimés.

Erreur constatée au test de faisabilité et sur tout le corpus : Audiveris lit une pause
multiple (barre épaisse sur la ligne du milieu, nombre au-dessus) comme UNE mesure de
pause. La partie est alors décalée : dans une flûte, 19 mesures devenues 4.

Deux contrôles, sur les mesures lues par Audiveris :
- une mesure qui ne contient qu'un silence est examinée dans l'image : si l'on y voit
  une barre épaisse sur la ligne du milieu, c'est une pause multiple ; son nombre est lu
  au-dessus (problème « multirest_missed ») ;
- les numéros de mesure imprimés en début de ligne sont comparés à la numérotation
  calculée : s'ils « sautent » de plus, il manque des mesures entre les deux lignes,
  sans doute une pause multiple comptée pour une (problème « measure_number_mismatch »).

La lecture des nombres est confiée à une fonction `read_number(morceau d'image) → int`
(Tesseract en vrai, une fonction de test dans les tests).
"""

from collections.abc import Callable

import cv2
import numpy as np

from recomuse.model.score import Measure, Part, ScoreModel
from recomuse.validation.geometry import PageGeometries, StaffGeometry
from recomuse.validation.issues import Fix, Issue

NumberReader = Callable[[np.ndarray], int | None]

# Barre de pause multiple : au moins 0,6 interligne d'épaisseur sur au moins 2,5 interlignes.
HBAR_MIN_THICKNESS = 0.6
HBAR_MIN_LENGTH = 2.5

# Encre : pixels plus sombres que ce niveau de gris.
INK_LEVEL = 128

# Un nombre est fait des traits d'encre à moins de 3 interlignes de son centre.
NUMBER_REACH = 3.0

# Un saut de numérotation qu'aucune mesure de pause n'explique n'est retenu que s'il est
# petit (une ou deux mesures en trop ou en moins) : sinon c'est une erreur de lecture.
MAX_UNEXPLAINED_JUMP = 2


def _rest_only(measure: Measure) -> bool:
    return bool(measure.events) and all(s.kind == "rest" for s in measure.events) \
        and not any(s.kind == "multirest" for s in measure.attributes)


def find_hbar(gray: np.ndarray, staff: StaffGeometry, x0: float,
              x1: float) -> tuple[int, int] | None:
    """Barre de pause multiple entre x0 et x1 sur la ligne du milieu : (début, fin) en pixels."""
    il = staff.interline
    middle = staff.y_of(4)
    top, bottom = int(middle - 0.7 * il), int(middle + 0.7 * il)
    left, right = int(x0 + il), int(x1 - il)
    if right - left < HBAR_MIN_LENGTH * il or top < 0 or bottom >= gray.shape[0]:
        return None
    band = gray[top:bottom, left:right] < INK_LEVEL
    thick = band.sum(axis=0) >= HBAR_MIN_THICKNESS * il
    best, start = None, None
    for index, value in enumerate(list(thick) + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            longer = best is None or index - start > best[1] - best[0]
            if index - start >= HBAR_MIN_LENGTH * il and longer:
                best = (start, index)
            start = None
    return (left + best[0], left + best[1]) if best else None


def tight_number(crop: np.ndarray, interline: float, center: float) -> np.ndarray | None:
    """Recadre un nombre dans un morceau d'image : l'encre proche de l'abscisse `center`,
    en noir et blanc, avec une marge blanche et agrandie deux fois (Tesseract lit mieux
    un nombre seul, bien net et assez grand)."""
    if crop.size == 0:
        return None
    ink = (crop < INK_LEVEL).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    boxes = [stats[i] for i in range(1, count)
             if stats[i][4] >= 0.02 * interline ** 2
             and abs(stats[i][0] + stats[i][2] / 2 - center) <= NUMBER_REACH * interline]
    if not boxes:
        return None
    x0, x1 = min(b[0] for b in boxes), max(b[0] + b[2] for b in boxes)
    y0, y1 = min(b[1] for b in boxes), max(b[1] + b[3] for b in boxes)
    piece = np.where(crop[y0:y1, x0:x1] < INK_LEVEL, 0, 255).astype(np.uint8)
    piece = cv2.copyMakeBorder(piece, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    return cv2.resize(piece, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def _number_above(gray: np.ndarray, staff: StaffGeometry, x0: float, x1: float,
                  read_number: NumberReader | None) -> int | None:
    """Nombre écrit au-dessus de la portée, centré entre x0 et x1 (pause multiple)."""
    if read_number is None:
        return None
    il = staff.interline
    left = max(0, int(x0 - il))
    crop = gray[max(0, int(staff.top - 4 * il)):int(staff.top - 0.3 * il), left:int(x1 + il)]
    piece = tight_number(crop, il, (x0 + x1) / 2 - left)
    return read_number(piece) if piece is not None else None


def check_multirests(model: ScoreModel, geometries: PageGeometries,
                     read_number: NumberReader | None = None) -> list[Issue]:
    issues = []
    for part in model.parts:
        for measure in part.measures:
            multirest = next((s for s in measure.attributes if s.kind == "multirest"), None)
            if multirest is not None:
                issue = _check_multirest_count(model, part, measure, multirest, geometries,
                                               read_number)
                if issue is not None:
                    issues.append(issue)
                continue
            # Mesure de pause seule, ou vide (Audiveris en produit pour une pause multiple).
            if measure.events and (not _rest_only(measure)
                                   or measure.events[0].source != "audiveris"):
                continue
            if not measure.events and (measure.page is None
                                       or model.page(measure.page).source != "audiveris"):
                continue
            page = model.page(measure.page) if measure.page else None
            if page is None or page.image_path is None or measure.bbox is None:
                continue
            x, y, w, h = measure.bbox
            staff = geometries.staff_at(page.image_path, x + w / 2, y + h / 2)
            if staff is None:
                continue
            gray = geometries.image(page.image_path)
            bar = find_hbar(gray, staff, x, x + w)
            if bar is None:
                continue
            count = _number_above(gray, staff, bar[0], bar[1], read_number)
            issues.append(Issue(
                code="multirest_missed", part_id=part.id, measure_numbers=[measure.number],
                severity="error", confidence=0.6 if count else 0.5,
                symbol_ids=[s.id for s in measure.events],
                details={"count": count, "empty_measure": not measure.events},
                action={"set_multirest": count, "measure_id": measure.id},
            ))
    return issues


def _check_multirest_count(model: ScoreModel, part: Part, measure: Measure, multirest,
                           geometries: PageGeometries, read_number: NumberReader | None):
    """Pause multiple reconnue, mais dont le nombre manque ou vaut 1 (Audiveris écrit
    souvent 1 faute d'avoir lu le chiffre) : on relit le nombre au-dessus de la barre."""
    count = multirest.value.get("count")
    if count and count > 1 or multirest.source == "vector":
        return None
    read = None
    page = model.page(multirest.page) if multirest.page else None
    if page is not None and page.image_path and multirest.bbox is not None:
        x, y, w, h = multirest.bbox
        staff = geometries.staff_at(page.image_path, x + w / 2, y + h / 2)
        if staff is not None:
            read = _number_above(geometries.image(page.image_path), staff, x, x + w, read_number)
    if read and read > 1:
        # Le nombre relu est une PROPOSITION : les chiffres « manuscrits » sont mal lus.
        return Issue(code="multirest_missed", part_id=part.id, measure_numbers=[measure.number],
                     severity="error", confidence=0.6, symbol_ids=[multirest.id],
                     details={"count": read, "read_by_audiveris": count},
                     fixes=[Fix(multirest.id, {"count": read})])
    return Issue(code="multirest_count_unknown", part_id=part.id,
                 measure_numbers=[measure.number], severity="warning", confidence=0.8,
                 symbol_ids=[multirest.id], details={"read_by_audiveris": count})


def _system_starts(part: Part) -> list[Measure]:
    """Première mesure de chaque ligne (système) de la partie."""
    starts, seen = [], set()
    for measure in part.measures:
        key = (measure.page, measure.system)
        if measure.system is not None and key not in seen:
            seen.add(key)
            starts.append(measure)
    return starts


def _printed_number(model: ScoreModel, measure: Measure, geometries: PageGeometries,
                    read_number: NumberReader | None) -> int | None:
    """Numéro imprimé au-dessus du début d'une ligne : connu (lecture vectorielle) ou lu."""
    if measure.printed_number is not None:
        return measure.printed_number
    page = model.page(measure.page) if measure.page else None
    if read_number is None or page is None or page.image_path is None or measure.bbox is None:
        return None
    x, y, w, h = measure.bbox
    staff = geometries.staff_at(page.image_path, x + w / 2, y + h / 2)
    if staff is None:
        return None
    il = staff.interline
    gray = geometries.image(page.image_path)
    # Le numéro est au-dessus de la portée, au début de la ligne, plus haut que le sommet
    # de la clé de sol (qui dépasse d'environ 1,5 interligne).
    left = max(0, int(staff.x0 - 2 * il))
    crop = gray[max(0, int(staff.top - 4 * il)):int(staff.top - 1.6 * il),
                left:int(staff.x0 + 4 * il)]
    piece = tight_number(crop, il, staff.x0 + il - left)
    return read_number(piece) if piece is not None else None


def check_numbering(model: ScoreModel, geometries: PageGeometries,
                    read_number: NumberReader | None = None) -> list[Issue]:
    issues = []
    for part in model.parts:
        anchors = [(m, _printed_number(model, m, geometries, read_number))
                   for m in _system_starts(part)]
        anchors = _increasing([(m, n) for m, n in anchors if n is not None])
        issues += _numbering_jumps(part, anchors)
    return issues


def _increasing(anchors: list[tuple[Measure, int]]) -> list[tuple[Measure, int]]:
    """Garde la plus longue suite de numéros imprimés qui croissent d'une ligne à l'autre :
    un numéro qui casse l'ordre est une erreur de lecture."""
    if not anchors:
        return []
    best = [1] * len(anchors)
    previous = [-1] * len(anchors)
    for i in range(len(anchors)):
        for j in range(i):
            if anchors[j][1] < anchors[i][1] and best[j] + 1 > best[i]:
                best[i], previous[i] = best[j] + 1, j
    index = max(range(len(anchors)), key=lambda k: best[k])
    kept = []
    while index != -1:
        kept.append(anchors[index])
        index = previous[index]
    return kept[::-1]


def _numbering_jumps(part: Part, anchors: list[tuple[Measure, int]]) -> list[Issue]:
    """Compare l'écart entre numéros imprimés à l'écart entre numéros calculés.

    Une levée peut décaler toute la numérotation (écart constant) : seul un CHANGEMENT
    d'écart compte, et il doit se confirmer au numéro suivant (sinon c'est sans doute une
    erreur de lecture du nombre).
    """
    issues = []
    offsets = [printed - measure.number for measure, printed in anchors]
    for i in range(1, len(anchors)):
        jump = offsets[i] - offsets[i - 1]
        if jump == 0:
            continue
        confirmed = i + 1 >= len(anchors) or offsets[i + 1] == offsets[i]
        if not confirmed:
            continue
        before, after = anchors[i - 1][0], anchors[i][0]
        between = [m for m in part.measures if before.number <= m.number < after.number]
        candidates = [m for m in between if _rest_only(m)]
        issue = Issue(
            code="measure_number_mismatch", part_id=part.id,
            measure_numbers=[m.number for m in between] or [after.number],
            severity="error", confidence=0.7,
            details={"printed_before": anchors[i - 1][1], "printed_after": anchors[i][1],
                     "computed_before": before.number, "computed_after": after.number,
                     "missing": jump},
        )
        if not (jump > 0 and candidates) and abs(jump) > MAX_UNEXPLAINED_JUMP:
            continue   # saut inexpliqué et grand : numéro mal lu
        if jump > 0 and len(candidates) == 1:
            # Une seule mesure de pause entre les deux lignes : c'est elle, la pause multiple.
            issue.confidence = 0.85
            issue.action = {"set_multirest": candidates[0].length + jump,
                            "measure_id": candidates[0].id}
            issue.symbol_ids = [s.id for s in candidates[0].events]
        issues.append(issue)
    return issues
