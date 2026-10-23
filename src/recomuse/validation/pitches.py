"""Contrôle des hauteurs d'après la position des têtes sur la portée.

Erreur constatée au test de faisabilité : des notes au-dessus de la portée lues une octave
trop bas (do6 lu do5). Et sur le corpus : Audiveris prend parfois la clé de sol d'une
police « manuscrite » (Jazz, Inkpen) pour une clé de sol octaviée (un 8 en dessous),
ce qui baisse TOUTE la partie d'une octave.

Deux contrôles :
- clé octaviée peu sûre → problème « clef_octave_suspicious », avec la correction de la clé
  ET de toutes les notes qu'elle gouverne (une seule réponse corrige toute la partie) ;
- chaque note lue par Audiveris : la hauteur est recalculée d'après la position du centre
  de sa tête entre les lignes de la portée (retrouvées dans l'image) et la clé en vigueur ;
  si elle diffère, problème « note_position_mismatch » avec la hauteur recalculée.
Les notes de la lecture vectorielle sont exactes : elles ne sont pas contrôlées.
"""

from recomuse.model.score import Part, ScoreModel, Symbol
from recomuse.validation.geometry import PageGeometries
from recomuse.validation.issues import Fix, Issue
from recomuse.vector import pitch

# Une clé octaviée lue avec une confiance inférieure est suspecte.
SUSPICIOUS_CLEF_CONFIDENCE = 0.6

# La tête doit être bien centrée sur une ligne ou un interligne (part d'un demi-interligne).
POSITION_TOLERANCE = 0.3

# Au moins 3 notes d'une mesure, et plus de la moitié, en désaccord avec leur position :
# la mesure est mal appariée (MusicXML ↔ .omr), on ne conclut rien sur ses notes.
MISALIGNED_MIN = 3
MISALIGNED_SHARE = 0.5

# Clé MusicXML (signe) → clé de la lecture vectorielle, pour calculer les hauteurs.
CLEF_NAMES = {"G": "treble", "F": "bass", "C": "c"}


def expected_pitch(clef: dict, position: int) -> tuple[str, int] | None:
    """Note (degré, octave) à une position de la portée, pour une clé MusicXML."""
    name = CLEF_NAMES.get(clef.get("sign"))
    if name is None or clef.get("line") is None:
        return None
    clef_position = (clef["line"] - 1) * 2
    step, octave = pitch.pitch_at(name, clef_position, position)
    return step, octave + (clef.get("octave_change") or 0)


def check_pitches(model: ScoreModel, geometries: PageGeometries | None = None) -> list[Issue]:
    geometries = geometries or PageGeometries()
    issues = []
    for part in model.parts:
        issues += _check_clefs(part)
        issues += _check_positions(model, part, geometries)
    return issues


def notes_with_clef(part: Part):
    """(mesure, symbole, clé en vigueur) pour chaque note de la partie, dans l'ordre."""
    clef: Symbol | None = None
    for measure in part.measures:
        for symbol in measure.attributes:
            if symbol.kind == "clef":
                clef = symbol
        for symbol in measure.events:
            if symbol.kind == "note":
                yield measure, symbol, clef


def _check_clefs(part: Part) -> list[Issue]:
    issues = []
    for clef in [s for m in part.measures for s in m.attributes if s.kind == "clef"]:
        change = clef.value.get("octave_change") or 0
        if not change or clef.source == "vector" or clef.confidence >= SUSPICIOUS_CLEF_CONFIDENCE:
            continue
        notes = [(m, s) for m, s, c in notes_with_clef(part) if c is clef and s.value.get("octave")]
        issue = Issue(
            code="clef_octave_suspicious", part_id=part.id,
            measure_numbers=sorted({m.number for m, _ in notes}) or [],
            severity="error", confidence=round(1 - clef.confidence, 2),
            symbol_ids=[clef.id] + [s.id for _, s in notes],
            details={"octave_change": change, "clef_confidence": clef.confidence,
                     "notes": len(notes)},
        )
        issue.fixes.append(Fix(clef.id, {"octave_change": 0}))
        issue.fixes += [Fix(s.id, {"octave": s.value["octave"] - change}) for _, s in notes]
        issues.append(issue)
    return issues


def _check_positions(model: ScoreModel, part: Part, geometries: PageGeometries) -> list[Issue]:
    issues = []
    checked: dict[str, int] = {}     # notes contrôlées par mesure
    for measure, note, clef in notes_with_clef(part):
        if note.source != "audiveris" or note.bbox is None or clef is None or note.page is None:
            continue
        page = model.page(note.page)
        if page is None or page.image_path is None:
            continue
        x, y, w, h = note.bbox
        cx, cy = x + w / 2, y + h / 2
        staff = geometries.staff_at(page.image_path, cx, cy)
        if staff is None:
            continue
        value = staff.position(cy)
        position = round(value)
        if abs(value - position) > POSITION_TOLERANCE:
            continue   # tête mal centrée : on ne conclut pas
        expected = expected_pitch(clef.value, position)
        if expected is None:
            continue
        checked[measure.id] = checked.get(measure.id, 0) + 1
        step, octave = expected
        if (note.value.get("step"), note.value.get("octave")) == (step, octave):
            continue
        same_step = note.value.get("step") == step
        issues.append(_issue(part, measure, note, step, octave, position, same_step))
    return _drop_misaligned(issues, checked)


def _issue(part: Part, measure, note: Symbol, step: str, octave: int, position: int,
           same_step: bool) -> Issue:
    return Issue(
        code="note_position_mismatch", part_id=part.id, measure_numbers=[measure.number],
        severity="error" if same_step else "warning",
        confidence=0.85 if same_step else 0.6,
        symbol_ids=[note.id],
        details={"read": f"{note.value.get('step')}{note.value.get('octave')}",
                 "from_position": f"{step}{octave}", "position": position,
                 "measure_id": measure.id},
        fixes=[Fix(note.id, {"step": step, "octave": octave})],
    )


def _drop_misaligned(issues: list[Issue], checked: dict[str, int]) -> list[Issue]:
    """Si la plupart des notes d'une mesure sont en désaccord avec leur position, c'est que
    les notes du MusicXML ont été associées aux mauvaises têtes : les écarts ne disent rien
    des notes elles-mêmes. On ne garde que les écarts isolés."""
    per_measure: dict[str, int] = {}
    for issue in issues:
        measure_id = issue.details["measure_id"]
        per_measure[measure_id] = per_measure.get(measure_id, 0) + 1
    kept = []
    for issue in issues:
        measure_id = issue.details["measure_id"]
        wrong, total = per_measure[measure_id], checked.get(measure_id, 1)
        if wrong >= MISALIGNED_MIN and wrong > MISALIGNED_SHARE * total:
            continue
        kept.append(issue)
    return kept
