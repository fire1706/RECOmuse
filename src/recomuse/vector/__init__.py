"""Lecture directe des PDF vectoriels (police de musique et traits), sans passer par l'image.

Fichiers du module :
- glyphs.py     : signification des caractères des polices de musique (table Sonata) ;
- primitives.py : extraction des caractères, textes et traits d'une page ;
- staves.py     : portées, barres de mesure, systèmes ;
- pitch.py      : hauteur des notes (clé, position, armure, altérations) ;
- rhythm.py     : durées (hampes, ligatures, crochets, points, nolets, liaisons) ;
- reader.py     : lecture d'une page (mesures, clés, armures, chiffrages, notes, durées...) ;
- score.py      : lecture d'un PDF entier, résumé par partie.

Tâche 4b-1 : structure et hauteurs. Tâche 4b-2 : durées et contrôle des mesures.

Essai à la main :  python -m recomuse.vector partition.pdf --pages 1-2 --notes
"""

from recomuse.vector.score import PartMeasure, VectorScore, read_vector_pdf

__all__ = ["PartMeasure", "VectorScore", "read_vector_pdf"]
