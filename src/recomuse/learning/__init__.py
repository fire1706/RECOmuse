"""Apprentissage : journal des corrections, règles apprises, mémoire des partitions,
packs d'apprentissage.

- journal.py     : le journal des corrections (en ajout seul) ;
- corrections.py : le service UNIQUE par lequel passe toute correction (journal + modèle) ;
- rules.py       : règles apprises des réponses de l'utilisateur (même réponse, même doute) ;
- memory.py      : empreinte des pages, pour reconnaître une partition déjà lue et
                   reprendre ses corrections.
Les packs d'apprentissage viendront à la tâche 13.
"""
