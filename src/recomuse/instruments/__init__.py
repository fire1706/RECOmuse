"""Instruments et transposition.

Fichiers du module :
- instruments.json : la table des instruments (modifiable sans toucher au code) : noms
                     sous lesquels ils apparaissent, étendue écrite, versions (tonalité,
                     clé, transposition) ;
- table.py         : lecture de la table, intervalles, reconnaissance de l'instrument et
                     de sa version d'après le nom de la partie et sa clé ;
- transpose.py     : transposition d'une partition (notes, armures, clé), pour un autre
                     instrument ou d'un intervalle, avec l'octave conseillée ;
- parts.py         : instrument d'une partition enregistrée, et partition transposée
                     enregistrée comme une nouvelle partition.
"""
