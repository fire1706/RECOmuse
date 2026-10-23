"""Problèmes trouvés par le validateur.

Un problème (Issue) dit ce qui ne va pas (un code court, traduit par l'interface), où
(partie, mesures, symboles), pourquoi (sa cause, qui sert à regrouper les questions :
une seule réponse peut corriger plusieurs mesures, tâche 8), et ce qu'on propose
(une correction prête à passer par le service de corrections, si on sait la faire).
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# Codes des problèmes (traduits par l'interface).
IssueCode = Literal[
    "measure_duration",          # durée de la mesure différente de son chiffrage
    "time_signature_missed",     # suite de mesures de même durée fausse : chiffrage manqué
    "time_signature_missing",    # partie sans aucun chiffrage
    "clef_octave_suspicious",    # clé octaviée peu sûre : toute la partie à l'octave ?
    "note_position_mismatch",    # hauteur lue ≠ hauteur d'après la position sur la portée
    "multirest_missed",          # pause multiple lue comme une seule mesure
    "multirest_count_unknown",   # pause multiple dont le nombre n'a pas été lu
    "measure_number_mismatch",   # numérotation calculée ≠ numéro de mesure imprimé
    "note_out_of_range",         # note hors de la tessiture de l'instrument
]

Severity = Literal["error", "warning", "info"]


@dataclass
class Fix:
    """Une correction proposée pour un symbole : les champs qui changent."""

    symbol_id: str
    value: dict[str, Any]


@dataclass
class Issue:
    code: IssueCode
    part_id: str
    measure_numbers: list[int]
    severity: Severity = "warning"
    # Confiance du validateur dans ce diagnostic (0 à 1) : sert à décider s'il faut
    # demander à l'utilisateur ou si une règle apprise suffit (tâches 8 et 12).
    confidence: float = 0.5
    symbol_ids: list[str] = field(default_factory=list)
    # Détails pour le message : durée lue, attendue, chiffrage proposé...
    details: dict[str, Any] = field(default_factory=dict)
    # Corrections proposées (vides si le validateur ne sait que signaler).
    fixes: list[Fix] = field(default_factory=list)
    # Correction qui demande d'ajouter ou de retirer des symboles (pas encore applicable
    # par le service de corrections) : décrite ici, ex. {"set_multirest": 12}.
    action: dict[str, Any] = field(default_factory=dict)

    @property
    def cause(self) -> str:
        """Clé de regroupement : deux problèmes de même cause dans une même partie peuvent
        être réglés par une seule réponse."""
        return f"{self.part_id}:{self.code}"

    def to_dict(self) -> dict:
        return {**asdict(self), "cause": self.cause}


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def by_code(self, code: str) -> list[Issue]:
        return [i for i in self.issues if i.code == code]

    def to_dict(self) -> dict:
        return {"issues": [i.to_dict() for i in self.issues],
                "counts": {code: len(self.by_code(code))
                           for code in sorted({i.code for i in self.issues})}}
