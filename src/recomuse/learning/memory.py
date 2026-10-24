"""Mémoire des partitions : reconnaître une partition déjà lue et reprendre ses corrections.

Chaque page lue reçoit une empreinte : l'image réduite à une petite grille, dont on garde
seulement « plus clair ou plus sombre que sa voisine » (256 bits). Deux lectures du même
PDF, ou du même scan, donnent la même empreinte ; une page différente en donne une très
différente. Un léger écart (quelques bits) est toléré : même fichier réenregistré, page
un peu recadrée.

Quand une partition ouverte a les mêmes pages qu'une partition déjà corrigée, ses
corrections sont rejouées une à une sur la nouvelle lecture (source « rule », raison
« memory:<numéro> » dans le journal), et les réponses aux questions reprises : les
questions déjà réglées ne sont pas reposées. Une correction dont le symbole n'existe
plus (la lecture a changé) est passée.
Les corrections peuvent aussi venir d'un pack d'apprentissage (learning/packs.py) : la
même partie, corrigée par un autre membre de la fanfare.
"""

import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from recomuse.importer.loading import read_gray
from recomuse.learning.corrections import CorrectionService, NewSymbol
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.score import ScoreModel
from recomuse.model.store import load_model

# Grille de l'empreinte : 16 × 16 comparaisons = 256 bits.
GRID = 16
# Écart toléré entre deux empreintes de la même page (bits différents).
MAX_DISTANCE = 12


def fingerprint(pixels: np.ndarray) -> str:
    """Empreinte d'une image de page (« dHash » sur 256 bits), en 64 chiffres hexadécimaux."""
    small = cv2.resize(pixels, (GRID + 1, GRID), interpolation=cv2.INTER_AREA).astype(int)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:064x}"


def distance(a: str, b: str) -> int:
    """Nombre de bits différents entre deux empreintes."""
    return (int(a, 16) ^ int(b, 16)).bit_count()


def page_fingerprints(model: ScoreModel) -> dict[int, str]:
    """Empreinte de chaque page de musique de la partition (dont l'image existe)."""
    result = {}
    for page in model.pages:
        if page.source == "none" or not page.image_path or not Path(page.image_path).is_file():
            continue
        result[page.number] = fingerprint(read_gray(Path(page.image_path)))
    return result


def store(conn: sqlite3.Connection, score_id: int, prints: dict[int, str]) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO page_fingerprints (score_id, page_number, fingerprint)"
            " VALUES (?, ?, ?)", [(score_id, n, f) for n, f in prints.items()])


def find_previous(conn: sqlite3.Connection, prints: dict[int, str],
                  exclude: set[int] | None = None) -> int | None:
    """La partition déjà lue la plus récente qui a les mêmes pages (dans le même ordre),
    et dont l'utilisateur a corrigé quelque chose ou répondu à une question."""
    if not prints:
        return None
    wanted = [prints[n] for n in sorted(prints)]
    stored: dict[int, list[tuple[int, str]]] = {}
    for score_id, number, value in conn.execute(
            "SELECT score_id, page_number, fingerprint FROM page_fingerprints"):
        stored.setdefault(score_id, []).append((number, value))
    for score_id in sorted(stored, reverse=True):
        if score_id in (exclude or set()):
            continue
        pages = [value for _, value in sorted(stored[score_id])]
        if same_pages(pages, wanted) and _has_work(conn, score_id):
            return score_id
    return None


def _has_work(conn: sqlite3.Connection, score_id: int) -> bool:
    corrections = conn.execute("SELECT COUNT(*) FROM corrections WHERE score_id = ?",
                               (score_id,)).fetchone()[0]
    answers = conn.execute("SELECT COUNT(*) FROM question_answers WHERE score_id = ?"
                           " AND undone = 0", (score_id,)).fetchone()[0]
    return bool(corrections or answers)


def score_work(conn: sqlite3.Connection, score_id: int) -> tuple[list[dict], list[dict]]:
    """Le travail fait sur une partition, sous une forme simple (pour le rejouer ailleurs,
    ou le mettre dans un pack) : ses corrections encore en vigueur, dans l'ordre, et ses
    réponses aux questions."""
    history = CorrectionJournal(conn).list_for_score(score_id)
    reverted = {c.reverts_id for c in history if c.source == "revert"}
    corrections = [
        {"id": c.id, "group_id": c.group_id, "symbol_id": c.symbol_id,
         "symbol_kind": c.symbol_kind, "old_value": c.old_value, "new_value": c.new_value,
         "location": c.location}
        for c in history if c.source != "revert" and c.id not in reverted]
    rows = conn.execute(
        "SELECT question_key, code, choice_id, value, correction_ids, signature, choice_label"
        " FROM question_answers WHERE score_id = ? AND undone = 0 ORDER BY id", (score_id,))
    answers = [{"question_key": key, "code": code, "choice_id": choice_id, "value": value,
                "correction_ids": json.loads(ids), "signature": signature,
                "choice_label": label}
               for key, code, choice_id, value, ids, signature, label in rows.fetchall()]
    return corrections, answers


def replay(conn: sqlite3.Connection, service: CorrectionService, old_id: int,
           new_id: int) -> dict:
    """Rejoue sur la partition `new_id` les corrections encore en vigueur de `old_id`, puis
    reprend ses réponses aux questions. Renvoie {"from", "applied", "skipped", "answers"}."""
    corrections, answers = score_work(conn, old_id)
    return {"from": old_id,
            **replay_work(conn, service, corrections, answers, new_id, f"memory:{old_id}")}


def replay_work(conn: sqlite3.Connection, service: CorrectionService, corrections: list[dict],
                answers: list[dict], new_id: int, reason: str) -> dict:
    """Rejoue des corrections (et reprend des réponses), venant d'une partition de la base
    ou d'un pack d'apprentissage. Renvoie {"applied", "skipped", "answers"}."""
    groups: list[list[dict]] = []
    for correction in corrections:
        if correction["group_id"] and groups \
                and groups[-1][0]["group_id"] == correction["group_id"]:
            groups[-1].append(correction)
        else:
            groups.append([correction])

    mapping: dict[int, int] = {}      # n° de correction d'origine → n° de la reprise
    applied = skipped = 0
    for group in groups:
        model = load_model(conn, new_id)
        changes, removals, additions, order = [], [], [], ([], [], [])
        for c in group:
            if c["old_value"] is None:                    # ajout
                where = c["location"] or {}
                after = _event_before(model, where) if where.get("list") == "events" else None
                if not _measure_exists(model, where.get("measure_id")):
                    skipped += 1
                    continue
                additions.append(NewSymbol(where["measure_id"], c["symbol_kind"],
                                           dict(c["new_value"]), after=after))
                order[2].append(c["id"])
            elif not _symbol_exists(model, c["symbol_id"]):
                skipped += 1
            elif c["new_value"] is None:                  # suppression
                removals.append(c["symbol_id"])
                order[1].append(c["id"])
            else:
                changes.append((c["symbol_id"], dict(c["new_value"])))
                order[0].append(c["id"])
        if not (changes or removals or additions):
            continue
        ids = service.apply_group(new_id, changes, source="rule", reason=reason,
                                  additions=additions, removals=removals)
        mapping.update(zip(order[0] + order[1] + order[2], ids, strict=True))
        applied += len(ids)

    with conn:
        for answer in answers:
            ids = [mapping[i] for i in answer["correction_ids"] if i in mapping]
            conn.execute(
                "INSERT INTO question_answers (score_id, question_key, code, choice_id, value,"
                " correction_ids, signature, choice_label, answered_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'memory')",
                (new_id, answer["question_key"], answer["code"], answer["choice_id"],
                 answer["value"], json.dumps(ids), answer["signature"],
                 answer["choice_label"]))
    return {"applied": applied, "skipped": skipped, "answers": len(answers)}


def same_pages(stored: list[str], wanted: list[str]) -> bool:
    """Vrai si deux suites d'empreintes sont celles des mêmes pages, dans le même ordre."""
    return len(stored) == len(wanted) and all(
        distance(a, b) <= MAX_DISTANCE for a, b in zip(stored, wanted, strict=True))


def _symbol_exists(model: ScoreModel, symbol_id: str | None) -> bool:
    try:
        model.find(symbol_id or "")
        return True
    except KeyError:
        return False


def _measure_exists(model: ScoreModel, measure_id: str | None) -> bool:
    try:
        model.find_measure(measure_id or "")
        return True
    except KeyError:
        return False


def _event_before(model: ScoreModel, where: dict) -> str | None:
    """Événement après lequel remettre une note ajoutée (d'après sa place d'origine)."""
    try:
        _, measure = model.find_measure(where.get("measure_id") or "")
    except KeyError:
        return None
    index = where.get("index", 0)
    return measure.events[index - 1].id if 0 < index <= len(measure.events) else None
