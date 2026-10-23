"""Validateur musical : durées de mesure, octave recalculée depuis la position sur la portée,
pauses multiples, numéros de mesure imprimés, tessiture de l'instrument, comparaison entre
les parties d'un même morceau.

Fichiers du module :
- issues.py     : les problèmes trouvés (codes, corrections proposées) et le rapport ;
- durations.py  : durée des mesures, chiffrages manqués ou absents ;
- geometry.py   : portées retrouvées dans l'image de la page ;
- pitches.py    : clé octaviée suspecte, hauteur d'après la position des têtes ;
- numbering.py  : pauses multiples, numéros de mesure imprimés ;
- ranges.py     : tessiture des instruments (table instruments/instruments.json) ;
- validator.py  : tous les contrôles d'une partie (validate), application des corrections ;
- comparison.py : comparaison entre les parties d'un même morceau (compare_parts) :
                  mesures en trop ou en moins, chiffrages différents.

Essais à la main :  python -m recomuse.validation partition.pdf --pages 1-2 [--audiveris]
                    python -m recomuse.validation parties.pdf [autre.pdf...] --compare
"""

from recomuse.validation.comparison import compare_parts, part_refs
from recomuse.validation.issues import Fix, Issue, ValidationReport
from recomuse.validation.validator import apply_fixes, validate

__all__ = ["Fix", "Issue", "ValidationReport", "apply_fixes", "compare_parts", "part_refs",
           "validate"]
