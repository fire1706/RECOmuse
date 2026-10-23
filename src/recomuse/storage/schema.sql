-- =====================================================================
-- Schéma de la base locale de RECOmuse (version 1)
-- =====================================================================
-- Ce fichier est exécuté une seule fois, à la création de la base.
-- Les évolutions ultérieures passeront par des migrations numérotées
-- (voir storage/database.py), jamais en modifiant ce fichier après coup.
--
-- Les dates sont stockées en texte ISO 8601 UTC, par ex. 2026-10-23T09:15:00.123Z.
-- Les valeurs musicales (ancienne / nouvelle valeur, alternatives) sont stockées
-- en JSON, car leur forme dépend du type de symbole (note, pause, chiffrage...).

-- ---------------------------------------------------------------------
-- Partitions importées
-- ---------------------------------------------------------------------
-- Une ligne par fichier importé (une partie, un conducteur...).
-- On ne garde que le chemin et des informations descriptives :
-- le fichier lui-même n'est jamais copié dans la base.
CREATE TABLE scores (
    id           INTEGER PRIMARY KEY,
    title        TEXT,                    -- titre lu sur la partition (ou saisi)
    part_name    TEXT,                    -- instrument / partie, ex. « Euphonium sib »
    source_path  TEXT    NOT NULL,        -- chemin du PDF ou de l'image d'origine
    source_kind  TEXT    NOT NULL DEFAULT 'unknown'
                 CHECK (source_kind IN ('vector_pdf', 'scanned_pdf', 'image', 'unknown')),
    page_count   INTEGER CHECK (page_count IS NULL OR page_count > 0),
    imported_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------
-- Journal des corrections
-- ---------------------------------------------------------------------
-- TOUTE modification d'un symbole passe par ce journal (service unique :
-- recomuse.learning.journal). C'est la matière première de l'apprentissage :
-- règles apprises, mémoire des partitions, packs d'apprentissage.
--
-- Le journal est en AJOUT SEUL : on n'efface ni ne modifie jamais une ligne
-- (des déclencheurs l'interdisent plus bas). Pour annuler une correction,
-- on enregistre une nouvelle correction qui la référence via « reverts_id ».
CREATE TABLE corrections (
    id              INTEGER PRIMARY KEY,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Où se trouve le symbole corrigé ------------------------------------
    -- Pas de « ON DELETE » : une partition qui a des corrections ne peut pas être
    -- supprimée de la base, sinon le journal perdrait une partie de son histoire.
    score_id        INTEGER REFERENCES scores(id),
    page_number     INTEGER CHECK (page_number IS NULL OR page_number >= 1),
    measure_number  INTEGER,              -- numéro de mesure (tel qu'imprimé si connu)
    staff_number    INTEGER,              -- portée dans le système (1 = la plus haute)
    symbol_id       TEXT,                 -- identifiant du symbole dans le modèle interne
    symbol_kind     TEXT    NOT NULL,     -- ex. note, rest, time_signature, clef, text...

    -- Boîte du symbole sur la page, en pixels de l'image à 300 dpi
    bbox_x          REAL,
    bbox_y          REAL,
    bbox_width      REAL    CHECK (bbox_width IS NULL OR bbox_width >= 0),
    bbox_height     REAL    CHECK (bbox_height IS NULL OR bbox_height >= 0),

    -- Extrait d'image, chemin relatif au dossier des extraits (snippets/)
    snippet_path    TEXT,

    -- Ce qui a changé -----------------------------------------------------
    old_value       TEXT    CHECK (old_value IS NULL OR json_valid(old_value)),
    new_value       TEXT    NOT NULL CHECK (json_valid(new_value)),
    confidence      REAL    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    alternatives    TEXT    CHECK (alternatives IS NULL OR json_valid(alternatives)),

    -- D'où vient la correction --------------------------------------------
    --   question  : réponse de l'utilisateur à une question guidée
    --   manual    : édition manuelle dans la vue côte à côte
    --   rule      : appliquée automatiquement par une règle apprise
    --   validator : corrigée automatiquement par le validateur musical
    --   revert    : annulation d'une correction précédente
    source          TEXT    NOT NULL
                    CHECK (source IN ('question', 'manual', 'rule', 'validator', 'revert')),

    -- Une même réponse peut corriger plusieurs symboles : ils partagent le même group_id.
    group_id        TEXT,
    -- Cause du doute qui a mené à la question (ex. « octave_above_staff »).
    reason          TEXT,
    -- Correction annulée par celle-ci (uniquement quand source = 'revert').
    reverts_id      INTEGER REFERENCES corrections(id),

    CHECK ((source = 'revert') = (reverts_id IS NOT NULL))
);

CREATE INDEX idx_corrections_score   ON corrections(score_id);
CREATE INDEX idx_corrections_symbol  ON corrections(symbol_id);
CREATE INDEX idx_corrections_kind    ON corrections(symbol_kind);
CREATE INDEX idx_corrections_group   ON corrections(group_id);

-- Le journal ne peut être ni modifié ni effacé.
CREATE TRIGGER corrections_no_update
BEFORE UPDATE ON corrections
BEGIN
    SELECT RAISE(ABORT, 'Le journal des corrections est en ajout seul : modification interdite.');
END;

CREATE TRIGGER corrections_no_delete
BEFORE DELETE ON corrections
BEGIN
    SELECT RAISE(ABORT, 'Le journal des corrections est en ajout seul : suppression interdite.');
END;
