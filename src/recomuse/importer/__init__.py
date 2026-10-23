"""Import des PDF et des images : détection PDF vectoriel ou scanné, prétraitement
(redressement, 300 dpi).

Fichiers du module :
- detection.py  : type de chaque page d'un PDF (vectorielle, scannée, blanche) ;
- loading.py    : lecture des pages sous forme d'images en niveaux de gris ;
- preprocess.py : redressement, mise à l'échelle, mesure des portées ;
- pipeline.py   : enchaînement complet (import_score) et enregistrement en base ;
- errors.py     : erreurs d'import, avec un code traduit par l'interface.

Essai à la main :  python -m recomuse.importer partition.pdf
"""

from recomuse.importer.errors import ScoreImportError
from recomuse.importer.pipeline import ImportedPage, ImportedScore, import_score, register_score

__all__ = ["ImportedPage", "ImportedScore", "ScoreImportError", "import_score", "register_score"]
