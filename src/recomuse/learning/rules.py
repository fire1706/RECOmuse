"""Règles apprises : ce que l'utilisateur répond toujours, le logiciel le fait lui-même.

Chaque question a une « signature » : son type de doute et ce qui le caractérise, sans
ce qui est propre à une partition (« note lue au-dessus de la portée, une octave plus bas
que sa position », « clé lue avec un 8 en dessous »). Quand l'utilisateur a répondu au
moins MIN_EVIDENCE fois à des questions de même signature, sur au moins MIN_SCORES
partitions différentes (une seule partition peut avoir un défaut qui lui est propre), et
presque toujours de la même façon (MIN_AGREEMENT), c'est une règle : la prochaine
question de cette signature reçoit cette réponse sans être posée (source « rule »).

Les règles ne sont pas écrites quelque part : elles se déduisent à chaque fois des
réponses enregistrées (table question_answers). Une réponse contraire de l'utilisateur
affaiblit donc la règle tout de suite. L'utilisateur peut aussi en désactiver une
(table rule_settings). Les réponses à taper (un nombre de mesures) ne font pas de règle.
Les réponses reçues dans un pack d'apprentissage (learning/packs.py) comptent aussi.
"""

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from recomuse.model.score import ScoreModel
from recomuse.validation.issues import Issue

# Il faut au moins 3 réponses semblables, sur au moins 2 partitions, et 90 % d'entre
# elles identiques.
MIN_EVIDENCE = 3
MIN_SCORES = 2
MIN_AGREEMENT = 0.9
# Choix qui ne deviennent jamais des règles (ils demandent une valeur à taper).
NOT_LEARNED = {"count"}


@dataclass
class Rule:
    """Une règle apprise."""

    signature: dict[str, Any]
    key: str                  # signature en texte (identifiant de la règle)
    choice_id: str            # réponse appliquée (« accept », « keep »...)
    choice_label: str | None  # son étiquette, pour l'afficher (questions.choices.<label>)
    evidence: int             # nombre de réponses à cette signature
    agreeing: int             # dont identiques à la règle
    enabled: bool
    from_packs: int = 0       # réponses venues de packs d'apprentissage (d'autres membres)

    def to_dict(self) -> dict:
        return {"key": self.key, "signature": self.signature, "choice_id": self.choice_id,
                "choice_label": self.choice_label, "evidence": self.evidence,
                "agreeing": self.agreeing, "enabled": self.enabled,
                "from_packs": self.from_packs}


# --- Signatures ---------------------------------------------------------------------------


def signature_key(signature: dict[str, Any]) -> str:
    return json.dumps(signature, ensure_ascii=False, sort_keys=True)


def issue_signature(model: ScoreModel, issue: Issue) -> dict[str, Any] | None:
    """Signature d'un doute, ou None s'il ne peut pas donner de règle."""
    details = issue.details
    context: dict[str, Any] | None
    if issue.code == "clef_octave_suspicious":
        context = {"octave_change": details.get("octave_change")}
    elif issue.code == "note_position_mismatch":
        context = {"place": _place(details.get("position")),
                   "shift": _shift(details.get("read"), details.get("from_position"))}
    elif issue.code == "note_out_of_range":
        context = {"direction": details.get("direction"),
                   "instrument": details.get("instrument")}
    elif issue.code == "multirest_missed":
        count = issue.action.get("set_multirest") or details.get("count")
        context = {"count_read": bool(count and count > 1)}
    elif issue.code in ("time_signature_missed", "time_signature_missing",
                        "measure_number_mismatch", "part_measures_missing",
                        "part_measures_extra", "part_time_signature_differs"):
        context = {}
    else:
        context = None   # pause au nombre inconnu (à taper), ou doute sans question
    return None if context is None else {"code": issue.code, **context}


def _place(position: Any) -> str:
    """Où est la tête sur la portée (0 = ligne du bas, 8 = ligne du haut)."""
    if not isinstance(position, int | float):
        return "unknown"
    if position > 8:
        return "above"
    return "below" if position < 0 else "inside"


def _shift(read: Any, proposed: Any) -> str:
    """Écart entre la note lue et celle d'après sa position : une octave, ou autre."""
    if isinstance(read, str) and isinstance(proposed, str) and len(read) >= 2 \
            and read[0] == proposed[0] and read[1:] != proposed[1:]:
        return "octave"
    return "other"


# --- Règles -------------------------------------------------------------------------------


def learned_rules(conn: sqlite3.Connection) -> list[Rule]:
    """Toutes les règles apprises (activées ou non), les plus sûres d'abord. Les réponses
    des packs d'apprentissage importés comptent comme celles de l'utilisateur."""
    rows = conn.execute(
        "SELECT signature, choice_id, choice_label, 'local:' || score_id FROM question_answers"
        " WHERE undone = 0 AND answered_by = 'user' AND signature IS NOT NULL"
        " UNION ALL SELECT signature, choice_id, choice_label,"
        " 'pack:' || pack_id || ':' || score_key FROM pack_answers")
    answers: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    scores: dict[str, set[str]] = defaultdict(set)
    from_packs: Counter[str] = Counter()
    for key, choice_id, label, score in rows:
        answers[key].append((choice_id, label))
        scores[key].add(score)
        from_packs[key] += score.startswith("pack:")
    disabled = {row[0] for row in conn.execute(
        "SELECT signature FROM rule_settings WHERE enabled = 0")}
    rules = []
    for key, given in answers.items():
        choice_id, agreeing = Counter(c for c, _ in given).most_common(1)[0]
        if (choice_id in NOT_LEARNED or len(given) < MIN_EVIDENCE
                or len(scores[key]) < MIN_SCORES or agreeing / len(given) < MIN_AGREEMENT):
            continue
        label = next(lbl for c, lbl in reversed(given) if c == choice_id)
        rules.append(Rule(json.loads(key), key, choice_id, label, len(given), agreeing,
                          key not in disabled, from_packs[key]))
    return sorted(rules, key=lambda r: (-r.agreeing, r.key))


def rule_for(conn: sqlite3.Connection, key: str) -> Rule | None:
    """La règle activée pour cette signature, s'il y en a une."""
    return next((r for r in learned_rules(conn) if r.key == key and r.enabled), None)


def set_enabled(conn: sqlite3.Connection, key: str, enabled: bool) -> None:
    """Active ou désactive une règle (elle reste apprise, mais n'est plus appliquée)."""
    json.loads(key)   # une signature est toujours du JSON
    with conn:
        conn.execute("INSERT INTO rule_settings (signature, enabled) VALUES (?, ?) "
                     "ON CONFLICT(signature) DO UPDATE SET enabled = excluded.enabled",
                     (key, int(enabled)))
