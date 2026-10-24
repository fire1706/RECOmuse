"""Modèle interne de la partition : chaque symbole garde sa valeur, son extrait d'image,
sa position (page, boîte), sa confiance, ses alternatives et l'historique de ses valeurs
(ce dernier dans le journal des corrections).

Fichiers du module :
- score.py          : le modèle (ScoreModel → Part → Measure → Symbol), en JSON ;
- from_vector.py    : construction depuis la lecture vectorielle (pages vectorielles) ;
- omr.py            : lecture du projet d'Audiveris (.omr) : positions et confiances ;
- from_audiveris.py : construction depuis le MusicXML d'Audiveris + le .omr ;
- build.py          : assemblage, page par page (build_model) ;
- split.py          : séparation des parties d'un PDF qui les contient toutes (split_parts) ;
- conductor.py      : conducteurs (instruments, parties extraites, conducteur assemblé) ;
- store.py          : enregistrement dans la base locale ;
- snippets.py       : découpe des extraits d'image.

Les corrections passent toutes par learning/corrections.py (CorrectionService).

Essai à la main :  python -m recomuse.model partition.pdf --pages 1-2
"""

from recomuse.model.score import Measure, PageInfo, Part, ScoreModel, Symbol

__all__ = ["Measure", "PageInfo", "Part", "ScoreModel", "Symbol"]
