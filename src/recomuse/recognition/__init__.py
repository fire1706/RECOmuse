"""Reconnaissance des symboles : appel d'Audiveris en ligne de commande et lecture des textes
(Tesseract).

Fichiers du module :
- tools.py     : recherche d'Audiveris, de Tesseract et des fichiers de langues ;
- audiveris.py : construction du « livre » (TIFF multipage), appel et suivi d'Audiveris ;
- musicxml.py  : résumé des fichiers MusicXML produits ;
- ocr.py       : lecture de l'en-tête des pages avec Tesseract ;
- header.py    : titre, instrument, tempo et compositeurs tirés de l'en-tête ;
- pipeline.py  : enchaînement complet (recognize_score).

Essai à la main :  python -m recomuse.recognition partition.pdf --pages 1-2
"""

from recomuse.recognition.pipeline import RecognitionResult, recognize_score

__all__ = ["RecognitionResult", "recognize_score"]
