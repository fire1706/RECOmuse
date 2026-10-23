# RECOmuse — contexte du projet pour Claude Code

## Le projet
RECOmuse convertit des partitions PDF ou images en partitions numériques éditables :
MusicXML, MuseScore (.mscz) et MIDI.
Il est destiné aux membres de la Fanfare Royale d'Acoz (musiciens, pas informaticiens).
Quand le logiciel n'est pas sûr d'un symbole, il pose une question à l'utilisateur
(extrait de l'image + choix cliquables) au lieu de deviner.
Chaque correction est mémorisée pour que le logiciel s'améliore avec le temps.

Cahier des charges complet : `docs/cahier-des-charges.md` (à lire avant toute tâche importante).

## Règles de travail
- On avance tâche par tâche, selon le plan ci-dessous. Ne pas commencer la tâche suivante sans accord.
- L'utilisateur fait lui-même les commits et les push. Ne jamais lancer `git commit` ni `git push`.
  Proposer un message de commit à la fin de chaque tâche.
- Demander avant d'installer un logiciel ou un paquet sur la machine.
- Le dossier des partitions de l'utilisateur (corpus) est en LECTURE SEULE : ne jamais le modifier.
- Les partitions sont protégées par le droit d'auteur et le dépôt sera public :
  aucune partition (PDF, image, MusicXML, .omr) ne doit être ajoutée à Git.
  Le corpus de test local va dans `tests/corpus/`, qui est ignoré par Git.
- Noms de code (variables, fonctions, fichiers) en anglais ; commentaires et docstrings en français.
- Commenter le code clairement : l'utilisateur doit pouvoir le relire et le comprendre.
- Chaque module a ses tests (pytest côté Python, Vitest côté interface).

## Plateformes et contraintes
- Windows 10/11 et macOS (puces Apple et Intel). Application Mac non signée.
- 100 % hors ligne. Un seul installateur, aucun prérequis pour l'utilisateur final.
- Interface en français et en anglais (fichiers de traduction, aucun texte en dur dans les composants).
- MuseScore est installé chez la plupart des membres : export .mscz via MuseScore en ligne de commande,
  MusicXML en secours s'il est absent.
- Licence : AGPL-3.0 (comme Audiveris).

## Choix techniques
| Rôle | Technologie |
| --- | --- |
| Moteur | Python 3.12 |
| Reconnaissance des symboles | Audiveris 5.11, appelé en ligne de commande (`-batch -export`) |
| Lecture PDF | PyMuPDF |
| Traitement d'image | OpenCV |
| Lecture des textes | Tesseract (fr, nl, en, de) |
| Musique (transposition, MusicXML, MIDI) | music21 |
| Interface | React + TypeScript + Vite |
| Affichage des partitions | Verovio |
| Fenêtre du logiciel | pywebview (pont JS ↔ Python, pas de serveur HTTP) |
| Données locales | SQLite + dossier d'extraits d'images |
| Installateurs | PyInstaller + Inno Setup (Windows), .app dans un .dmg (macOS) |

## Architecture (modules du moteur)
1. `importer` : import des PDF/images, détection PDF vectoriel ou scanné, prétraitement (redressement, 300 dpi).
2. `recognition` : appel d'Audiveris + lecture des textes (titre, instrument, tempos).
3. `vector` : lecture directe des PDF vectoriels (police de musique + traits), sans passer par l'image.
4. `model` : modèle interne. Chaque symbole garde sa valeur, son extrait d'image, sa position (page, boîte),
   sa confiance, ses alternatives et l'historique de ses valeurs.
5. `validation` : durées de mesure, octave recalculée depuis la position sur la portée, pauses multiples,
   numéros de mesure imprimés, tessiture de l'instrument, comparaison entre les parties d'un même morceau.
6. `questions` : trie les doutes, regroupe ceux qui ont une même cause (une réponse peut corriger plusieurs mesures),
   consulte les règles apprises avant de décider de poser une question.
7. `learning` : journal des corrections (TOUTES les corrections passent par ce service unique),
   règles apprises, mémoire des partitions (empreinte de page), packs d'apprentissage.
8. `instruments` : table d'instruments modifiable (fichier de données), transposition, changement de clé.
9. `export` : MusicXML, MIDI à la hauteur réelle, MuseScore.

L'interface (`ui/`) montre le scan à gauche, le rendu Verovio à droite, et les questions au centre.

## Résultats du test de faisabilité (tâche 0)
Audiveris 5.11 testé sur deux partitions :
- PDF vectoriel Finale (Green Hill, euphonium sib en clé de sol, 5 pages) : 96 s, 170 mesures,
  mais 82 mesures de durée incorrecte, presque toutes dues à des changements de chiffrage ratés.
- PDF scanné 600 dpi (partie de flûte, 2 pages) : 74 s, rythmes bons, mais
  (a) notes au-dessus de la portée lues une octave trop bas (do6 lu do5) ;
  (b) pauses multiples comptées comme une seule mesure (19 mesures devenues 4, partie décalée de 15 mesures).
- Les langues Tesseract doivent être installées, sinon aucun texte n'est lu (nom de l'instrument perdu).
Le validateur doit détecter ces trois erreurs.

## Plan des tâches
- [x] 0. Test de faisabilité
- [x] 1. Cahier des charges
- [ ] 2. Squelette du projet : structure, pyproject, fenêtre pywebview + React, base SQLite (dont le schéma du journal), tests
- [ ] 3. Import et prétraitement
- [ ] 4. Intégration d'Audiveris et lecture des textes
- [ ] 4b. Lecture vectorielle directe des PDF vectoriels
- [ ] 5. Modèle interne et journal des corrections
- [ ] 6. Validateur musical
- [ ] 7. Comparaison entre parties
- [ ] 8. Interface de questions guidées
- [ ] 9. Vue côte à côte et édition manuelle
- [ ] 10. Instruments et transposition
- [ ] 11. Exports MusicXML, MIDI, MuseScore
- [ ] 12. Règles apprises et mémoire des partitions
- [ ] 13. Packs d'apprentissage
- [ ] 14. Conducteurs
- [ ] 15. Installateurs Windows et macOS, tests sur le corpus réel
Plus tard : percussions, photos au téléphone, piano et chant, modèle entraîné sur les corrections.
