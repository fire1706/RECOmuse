"""Le validateur : tous les contrôles musicaux, un rapport, et l'application des corrections.

Le validateur ne corrige rien de lui-même : il produit des problèmes (avec des corrections
proposées), et c'est le module des questions (tâche 8) qui décide, selon la confiance et
les règles apprises, de demander à l'utilisateur ou d'appliquer. Une correction appliquée
passe toujours par le service unique de corrections (learning/corrections.py).

La comparaison entre les parties d'un même morceau viendra à la tâche 7.
"""

from pathlib import Path

from recomuse.instruments.table import InstrumentTable
from recomuse.learning.corrections import CorrectionService
from recomuse.model.score import ScoreModel
from recomuse.recognition import tools
from recomuse.recognition.ocr import read_number
from recomuse.validation.durations import check_durations
from recomuse.validation.geometry import PageGeometries
from recomuse.validation.issues import Issue, ValidationReport
from recomuse.validation.numbering import NumberReader, check_multirests, check_numbering
from recomuse.validation.pitches import check_pitches
from recomuse.validation.ranges import check_clef_signs, check_ranges

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def tesseract_number_reader(work_dir: Path) -> NumberReader | None:
    """Lecture des nombres par Tesseract (None si Tesseract ou ses langues manquent)."""
    status = tools.check_tools()
    if status.tesseract is None or status.tessdata is None:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    return lambda pixels: read_number(status.tesseract, status.tessdata, pixels,
                                      work_dir / "nombre.png")


def validate(model: ScoreModel, read_number: NumberReader | None = None,
             table: InstrumentTable | None = None,
             geometries: PageGeometries | None = None) -> ValidationReport:
    """Passe la partition au crible de tous les contrôles."""
    geometries = geometries or PageGeometries()
    issues = (check_durations(model)
              + check_pitches(model, geometries)
              + check_multirests(model, geometries, read_number)
              + check_numbering(model, geometries, read_number))
    issues += check_clef_signs(model, table)
    # Une note qu'une clé suspecte (octaviée, ou d'un autre signe) va déjà déplacer n'est
    # pas signalée une seconde fois comme hors tessiture.
    covered = {symbol for issue in issues
               if issue.code in ("clef_octave_suspicious", "clef_sign_suspicious")
               for symbol in issue.symbol_ids}
    issues += [i for i in check_ranges(model, table) if not covered & set(i.symbol_ids)]
    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.part_id,
                               i.measure_numbers[0] if i.measure_numbers else 0))
    return ValidationReport(issues)


def apply_fixes(service: CorrectionService, score_id: int, issue: Issue,
                source: str = "validator") -> list[int]:
    """Applique les corrections proposées d'un problème, toutes ensemble (une réponse de
    l'utilisateur, ou une règle). Renvoie les numéros des corrections dans le journal."""
    if not issue.fixes:
        return []
    changes = [(fix.symbol_id, fix.value) for fix in issue.fixes]
    return service.apply_group(score_id, changes, source=source, reason=issue.code)
