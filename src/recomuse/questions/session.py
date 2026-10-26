"""Déroulement des questions d'une partition : les poser, enregistrer les réponses, annuler.

À chaque demande, la partition est revalidée et les questions recalculées : une réponse
peut en faire disparaître d'autres (corriger une pause multiple règle aussi le saut des
numéros de mesure qui la suivent). Si d'autres parties du même morceau ont été lues (même
titre), la partition leur est aussi comparée (validation/comparison.py).
Les questions déjà répondues ne sont plus posées, même si la réponse était « c'est
juste » (table question_answers).

Toutes les corrections passent par le service de corrections (learning/corrections.py).
Avant de poser une question, les règles apprises sont consultées (learning/rules.py) :
si l'utilisateur a toujours répondu de la même façon à des questions semblables, la
réponse est donnée sans lui demander (source « rule »). Il peut l'annuler comme ses
propres réponses ; la question lui est alors posée.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from recomuse import library, paths
from recomuse.learning import rules
from recomuse.learning.corrections import CorrectionService
from recomuse.model.measures import merge_with_next, split_after
from recomuse.model.score import ScoreModel
from recomuse.model.store import load_model
from recomuse.questions.images import question_image
from recomuse.questions.questions import Question, build_questions, check_items
from recomuse.validation.comparison import compare_parts, part_refs
from recomuse.validation.geometry import PageGeometries
from recomuse.validation.issues import Issue, ValidationReport
from recomuse.validation.validator import tesseract_number_reader, validate

# Changements du découpage en mesures qu'une réponse peut demander.
STRUCTURE_PLANS = {"merge_next": merge_with_next, "split_after": split_after}

# Nombre maximal de réponses données d'un coup par les règles apprises (garde-fou).
MAX_RULE_ANSWERS = 200


class QuestionError(RuntimeError):
    """Question ou réponse impossible (partition inconnue, question déjà répondue...)."""


class QuestionSession:
    """Questions des partitions ouvertes dans le logiciel."""

    def __init__(self, conn: sqlite3.Connection, service: CorrectionService | None = None,
                 work_dir: Path | None = None) -> None:
        self._conn = conn
        self._service = service or CorrectionService(conn)
        self._work_dir = work_dir
        # Images des pages et portées retrouvées : gardées pour la partition en cours
        # seulement (une page à 300 dpi pèse une dizaine de mégaoctets).
        self._geometries: tuple[int, PageGeometries] | None = None
        self._read_number = None
        self._current: dict[int, dict[str, Question]] = {}
        self._compared: dict[int, int] = {}     # nombre d'autres parties comparées

    # --- Demandes de l'interface ------------------------------------------------------------

    def state(self, score_id: int) -> dict:
        """Questions encore à poser, dans l'ordre, avec leur image."""
        model = self._model(score_id)
        questions, unasked = self._questions(score_id, model)
        geometries = self._page_images(score_id)
        listed = []
        for question in questions:
            data = question.to_dict()
            data["image"] = self._image(model, question, geometries)
            listed.append(data)
        return {"score_id": score_id, "questions": listed, "unasked": len(unasked),
                "checks": check_items(model, unasked),
                "compared_parts": self._compared.get(score_id, 0),
                "answered": self._answer_count(score_id),
                "answered_by_rules": self._answer_count(score_id, "rule"),
                "answered_by_memory": self._answer_count(score_id, "memory"),
                "can_undo": self._last_answer(score_id) is not None}

    def answer(self, score_id: int, key: str, choice_id: str, value: Any = None) -> dict:
        """Enregistre la réponse à une question et applique les corrections qu'elle
        implique. Renvoie le nouvel état des questions."""
        question = self._current.get(score_id, {}).get(key)
        if question is None:
            self._questions(score_id, self._model(score_id))
            question = self._current.get(score_id, {}).get(key)
        if question is None:
            raise QuestionError(f"Question inconnue ou déjà répondue : {key}")
        try:
            choice = question.choice(choice_id)
            fixes, additions = choice.changes(value)
        except (KeyError, ValueError) as error:
            raise QuestionError(f"Réponse impossible : {error}") from None

        self._record(score_id, question, choice, value, fixes, additions, "user")
        return self.state(score_id)

    def undo(self, score_id: int) -> dict:
        """Annule la dernière réponse : ses corrections sont annulées (dans le journal) et
        la question sera reposée."""
        last = self._last_answer(score_id)
        if last is None:
            raise QuestionError("Aucune réponse à annuler.")
        answer_id, correction_ids = last
        if correction_ids:
            self._service.revert_all(correction_ids)
        with self._conn:
            self._conn.execute("UPDATE question_answers SET undone = 1 WHERE id = ?",
                               (answer_id,))
        return self.state(score_id)

    # --- Interne ----------------------------------------------------------------------------

    def _model(self, score_id: int) -> ScoreModel:
        model = load_model(self._conn, score_id)
        if model is None:
            raise QuestionError(f"Aucune partition lue sous le n° {score_id}.")
        return model

    def _questions(self, score_id: int,
                   model: ScoreModel) -> tuple[list[Question], list[Issue]]:
        """Questions à poser, après avoir laissé les règles apprises répondre à celles
        qu'elles connaissent (une à la fois : chaque réponse change la partition, et donc
        les doutes suivants)."""
        for _ in range(MAX_RULE_ANSWERS):
            questions, unasked = self._open_questions(score_id, model)
            if not self._apply_one_rule(score_id, questions):
                break
            model = self._model(score_id)
        return questions, unasked

    def _open_questions(self, score_id: int,
                        model: ScoreModel) -> tuple[list[Question], list[Issue]]:
        report = validate(model, read_number=self._number_reader(),
                          geometries=self._page_images(score_id))
        report = ValidationReport(report.issues + self._comparison(score_id, model))
        questions, unasked = build_questions(model, report)
        answered = self._answered_keys(score_id)
        questions = [q for q in questions if q.key not in answered]
        self._current[score_id] = {q.key: q for q in questions}
        return questions, unasked

    def _apply_one_rule(self, score_id: int, questions: list[Question]) -> bool:
        """Répond à la première question qu'une règle activée connaît. Vrai si une
        réponse a été donnée. Une question dont l'utilisateur a annulé la réponse donnée
        par une règle lui est posée à lui."""
        known = {r.key: r for r in rules.learned_rules(self._conn) if r.enabled}
        if not known:
            return False
        refused = {row[0] for row in self._conn.execute(
            "SELECT question_key FROM question_answers WHERE score_id = ? AND undone = 1"
            " AND answered_by = 'rule'", (score_id,))}
        for question in questions:
            if question.signature is None or question.key in refused:
                continue
            rule = known.get(rules.signature_key(question.signature))
            choice = next((c for c in question.choices if rule and c.id == rule.choice_id),
                          None)
            if choice is None or choice.input is not None:
                continue
            fixes, additions = choice.changes()
            self._record(score_id, question, choice, None, fixes, additions, "rule")
            return True
        return False

    def _record(self, score_id: int, question: Question, choice, value: Any, fixes,
                additions, answered_by: str) -> None:
        """Applique les corrections d'une réponse et l'enregistre, avec la signature de
        la question (pour les règles apprises)."""
        ids: list[int] = []
        if choice.structure is not None:
            # Barre de mesure en trop ou manquée : le découpage en mesures change.
            plan = STRUCTURE_PLANS[choice.structure["op"]](self._model(score_id),
                                                           choice.structure["target"])
            ids = [self._service.restructure(
                score_id, plan, source="question" if answered_by == "user" else "rule",
                reason=question.code if answered_by == "user" else f"rule:{question.code}")]
        elif fixes or additions:
            ids = self._service.apply_group(
                score_id, [(f.symbol_id, f.value) for f in fixes],
                source="question" if answered_by == "user" else "rule",
                reason=question.code if answered_by == "user" else f"rule:{question.code}",
                additions=additions)
        signature = rules.signature_key(question.signature) if question.signature else None
        with self._conn:
            self._conn.execute(
                "INSERT INTO question_answers (score_id, question_key, code, choice_id, value,"
                " correction_ids, signature, choice_label, answered_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (score_id, question.key, question.code, choice.id,
                 json.dumps(value) if value is not None else None, json.dumps(ids),
                 signature, choice.label, answered_by))

    def _comparison(self, score_id: int, model: ScoreModel) -> list[Issue]:
        """Problèmes de cette partition trouvés en la comparant aux autres parties du
        morceau ; leur partie est ramenée à celle du modèle (« P1 »)."""
        refs, owners = [], []
        for other_id in library.piece_of(self._conn, score_id):
            other = model if other_id == score_id else load_model(self._conn, other_id)
            if other is not model and other is not None and (
                    other.transposed_from is not None or other.derived is not None):
                continue   # copie (transposée, extraite, assemblée) : elle doublerait l'autre
            for ref in part_refs([other] if other else []):
                refs.append(ref)
                owners.append(other_id)
        self._compared[score_id] = len(set(owners) - {score_id})
        if len(set(owners)) < 2:
            return []
        issues = []
        for issue in compare_parts(refs).issues:
            index = issue.details.get("ref_index")
            if index is not None and owners[index] == score_id:
                issue.part_id = refs[index].part.id
                issues.append(issue)
        return issues

    def _page_images(self, score_id: int) -> PageGeometries:
        if self._geometries is None or self._geometries[0] != score_id:
            self._geometries = (score_id, PageGeometries())
        return self._geometries[1]

    def _number_reader(self):
        """Lecture des nombres (pauses multiples, numéros de mesure) par Tesseract, None s'il
        manque. Chaque morceau d'image n'est lu qu'une fois : la partition est revalidée
        après chaque réponse, et Tesseract met un cinquième de seconde par nombre."""
        if self._read_number is None:
            folder = (self._work_dir or paths.imports_dir()) / "validation"
            reader = tesseract_number_reader(folder)
            self._read_number = _remembered(reader) if reader else False
        return self._read_number or None

    def _image(self, model: ScoreModel, question: Question,
               geometries: PageGeometries) -> str | None:
        page = model.page(question.page) if question.page is not None else None
        if page is None or page.image_path is None or question.region is None:
            return None
        if not Path(page.image_path).is_file():
            return None
        try:
            return question_image(geometries.image(page.image_path), question.region,
                                  question.highlights)
        except (OSError, ValueError):
            return None    # la question reste posable, sans image

    def _answered_keys(self, score_id: int) -> set[str]:
        rows = self._conn.execute(
            "SELECT question_key FROM question_answers WHERE score_id = ? AND undone = 0",
            (score_id,))
        return {row[0] for row in rows}

    def _answer_count(self, score_id: int, answered_by: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM question_answers WHERE score_id = ? AND undone = 0"
        if answered_by is None:
            return self._conn.execute(sql, (score_id,)).fetchone()[0]
        return self._conn.execute(sql + " AND answered_by = ?",
                                  (score_id, answered_by)).fetchone()[0]

    def _last_answer(self, score_id: int) -> tuple[int, list[int]] | None:
        row = self._conn.execute(
            "SELECT id, correction_ids FROM question_answers WHERE score_id = ? AND undone = 0"
            " ORDER BY id DESC LIMIT 1", (score_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None


def _remembered(reader):
    """Le même lecteur de nombres, qui se souvient de ce qu'il a déjà lu."""
    known: dict[tuple, int | None] = {}

    def read(pixels):
        key = (pixels.shape, hashlib.sha1(pixels.tobytes()).hexdigest())
        if key not in known:
            known[key] = reader(pixels)
        return known[key]
    return read
