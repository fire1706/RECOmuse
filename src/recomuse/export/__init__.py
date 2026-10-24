"""Exports : MusicXML, MIDI à la hauteur réelle et MuseScore (.mscz).

Fichiers du module :
- notation.py  : outils communs (durées écrites, altérations à imprimer, parties) ;
- musicxml.py  : modèle interne → MusicXML 4.0 (avec la transposition de l'instrument) ;
- midi.py      : modèle interne → fichier MIDI, joué à la hauteur réelle ;
- musescore.py : MuseScore en ligne de commande (MusicXML → .mscz) ;
- files.py     : écriture des fichiers, MusicXML de secours si MuseScore manque ;
- mei.py       : modèle interne → MEI, pour l'affichage par Verovio (vue côte à côte).
"""
