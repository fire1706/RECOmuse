# RECOmuse
logiciel de reconnaissance de partition pour transposition

Convertit des partitions PDF ou images en partitions numériques éditables
(MusicXML, MuseScore, MIDI). Licence AGPL-3.0.

## Développement

Prérequis : Python 3.12 et Node.js LTS.

```bash
# Moteur Python (une seule fois)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

# Interface (une seule fois, puis après chaque modification de l'interface)
cd ui
npm install
npm run build
```

Lancer le logiciel : `.venv\Scripts\python -m recomuse`
(ajouter `--dev` avec `npm run dev` lancé dans `ui/` pour le rechargement automatique).
« Ouvrir une partition… » lit le fichier (un PDF peut contenir plusieurs parties : une
partition par partie), puis la zone du centre pose les questions une à une. Les parties
d'un même morceau (même titre, dans un seul PDF ou dans des fichiers séparés) sont
comparées entre elles : une partie qui s'écarte des autres donne aussi une question.
Vue côte à côte : à gauche la page d'origine (mesures encadrées), à droite la partition
reconnue dessinée par Verovio ; cliquer une mesure d'un côté la montre de l'autre.
Édition manuelle : la mesure choisie s'ouvre dans l'éditeur (au-dessus du rendu) : clé,
armure, chiffrage, pause multiple, et pour chaque note sa hauteur (flèches ↑ ↓), son
altération, sa durée, ses points, sa liaison ; ajouter ou supprimer (Suppr) une note.
Chaque modification est une correction du journal ; « Annuler ma dernière modification »
la défait.
Transposition : « Transposer… » réécrit la partie pour un autre instrument (par exemple
une partie de trombone en clé de fa pour un baryton en si♭ en clé de sol) ou d'un
intervalle, et crée une nouvelle partition ; la table des instruments est le fichier
`src/recomuse/instruments/instruments.json`.

Tests : `.venv\Scripts\python -m pytest` à la racine, `npm test` dans `ui/`.
Tests lents, sur demande : `-m corpus` (vraies partitions de `tests/corpus/` ou `test/corpus/`)
et `-m external` (vrais Audiveris et Tesseract).

### Programmes externes (reconnaissance)

- Audiveris 5.11 : `winget install audiveris.org.Audiveris`
- Tesseract 5 : `winget install UB-Mannheim.TesseractOCR`
- Langues de Tesseract `eng`, `fra`, `nld`, `deu`, version **standard** de
  https://github.com/tesseract-ocr/tessdata (pas « best » ni « fast », qu'Audiveris
  ne sait pas utiliser), à copier dans `%LOCALAPPDATA%\RECOmuse\tessdata`.

Les emplacements peuvent être imposés par les variables `RECOMUSE_AUDIVERIS`,
`RECOMUSE_TESSERACT` et `RECOMUSE_TESSDATA`.

Essais à la main : `python -m recomuse.importer fichier.pdf` (import seul),
`python -m recomuse.recognition fichier.pdf --pages 1-2` (import + reconnaissance),
`python -m recomuse.vector fichier.pdf --pages 1 --notes` (lecture vectorielle) et
`python -m recomuse.model fichier.pdf --pages 1-2` (modèle interne complet),
`python -m recomuse.validation fichier.pdf --pages 1-2 [--audiveris]` (validateur) et
`python -m recomuse.validation parties.pdf [autre.pdf...] --compare` (séparation des
parties d'un même PDF, puis comparaison des parties d'un même morceau).

Sur macOS, remplacer `py -3.12` par `python3.12` et `.venv\Scripts\python` par `.venv/bin/python`.

## Structure

- `src/recomuse/` : moteur Python (un dossier par module, voir `CLAUDE.md`)
- `src/recomuse/storage/schema.sql` : schéma de la base locale (journal des corrections)
- `ui/` : interface React + TypeScript (traductions dans `ui/src/locales/`)
- `tests/` : tests Python ; `tests/corpus/` (partitions de test) n'est jamais versionné
