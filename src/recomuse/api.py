"""Pont entre l'interface React et le moteur Python.

pywebview rend chaque méthode publique de la classe Api appelable depuis le
JavaScript de l'interface :  await window.pywebview.api.get_app_info()
Il n'y a pas de serveur HTTP pour l'API : les appels passent directement par pywebview.
Chaque appel s'exécute dans son propre fil d'exécution : l'interface peut demander où en
est la lecture d'un fichier (get_progress) pendant que open_file travaille. Les appels qui
touchent à la base passent UN PAR UN (verrou _db) : la connexion SQLite est partagée, et
deux demandes en même temps (après une correction, l'interface relit la page, le rendu,
la mesure et les questions d'un coup) se mélangeraient.

Règles :
- les méthodes renvoient des données simples (dict, list, str, nombres) que
  pywebview convertit en JSON pour l'interface ;
- les textes affichés à l'utilisateur ne sont PAS construits ici : l'interface
  les traduit elle-même (français / anglais) à partir de codes ;
- une erreur est renvoyée sous la forme {"error": code}, jamais comme une exception.
"""

import logging
import platform
import re
import sqlite3
import sys
import threading
from pathlib import Path

from recomuse import __version__, editing, library
from recomuse.export import files as exports
from recomuse.export.musescore import find_musescore
from recomuse.importer import ScoreImportError
from recomuse.importer.loading import IMAGE_EXTENSIONS
from recomuse.instruments import parts as instruments
from recomuse.learning import packs, rules
from recomuse.learning.corrections import CorrectionError, CorrectionService
from recomuse.learning.journal import CorrectionJournal
from recomuse.model.store import load_model
from recomuse.progress import ReadingCancelled, ReadingProgress
from recomuse.questions.session import QuestionError, QuestionSession
from recomuse.recognition.audiveris import AudiverisError
from recomuse.recognition.tools import ToolNotFoundError

log = logging.getLogger(__name__)

# Extensions proposées dans la fenêtre « Ouvrir ».
OPEN_EXTENSIONS = (".pdf", *sorted(IMAGE_EXTENSIONS))


def file_filter(label: str, extensions: tuple[str, ...] | list[str]) -> tuple[str]:
    """Filtre de fichiers des fenêtres « Ouvrir » et « Enregistrer sous » de pywebview.

    pywebview refuse un nom de filtre qui contient autre chose que des lettres, des
    chiffres et des espaces (parenthèses, apostrophe...), et une extension avec un tiret
    (« .recomuse-pack ») : il lève alors une erreur et la fenêtre ne s'ouvre PAS. Ces
    caractères sont donc retirés du nom, et une extension refusée devient « *.* » (tous
    les fichiers ; le contenu du fichier choisi est de toute façon vérifié ensuite).
    """
    name = " ".join(re.sub(r"[^\w ]+", " ", label).split()) or "RECOmuse"
    patterns = [f"*{ext}" if re.fullmatch(r"\.\w+", ext) else "*.*" for ext in extensions]
    return (f"{name} ({';'.join(dict.fromkeys(patterns))})",)


class LibraryError(RuntimeError):
    """Demande impossible sur les partitions ; `code` est traduit par l'interface."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Api:
    """Fonctions du moteur exposées à l'interface."""

    def __init__(self, conn: sqlite3.Connection, db_path: str) -> None:
        # Attributs « privés » (préfixe _) : pywebview n'expose pas ce qui commence par _.
        self._conn = conn
        self._db_path = db_path
        self._journal = CorrectionJournal(conn)
        self._corrections = CorrectionService(conn)
        self._questions = QuestionSession(conn, self._corrections)
        self._window = None                 # fenêtre pywebview, donnée par app.py
        self._reading: ReadingProgress | None = None   # lecture en cours (barre, annulation)
        self._busy = threading.Lock()       # une seule lecture de fichier à la fois
        self._db = threading.RLock()        # un seul appel à la fois sur la base

    def ping(self) -> str:
        """Vérifie que le pont fonctionne : renvoie toujours « pong »."""
        return "pong"

    def get_app_info(self) -> dict:
        """Informations affichées dans l'écran d'accueil de l'interface."""
        with self._db:
            count = self._journal.count()
        return {
            "version": __version__,
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "database_path": self._db_path,
            "correction_count": count,
        }

    # --- Partitions -----------------------------------------------------------------------

    def choose_file(self, filter_label: str) -> str | None:
        """Ouvre la fenêtre « Ouvrir » du système ; renvoie le fichier choisi (ou None).
        `filter_label` : nom du filtre de fichiers, traduit par l'interface."""
        if self._window is None:
            return None
        # Importé ici seulement : les tests n'ouvrent pas de fenêtre.
        import webview

        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False,
            file_types=file_filter(filter_label, OPEN_EXTENSIONS))
        return str(chosen[0]) if chosen else None

    def open_file(self, path: str) -> dict:
        """Lit un fichier : {"scores": [une partition par partie]} ou {"error": code}."""
        if not self._busy.acquire(blocking=False):
            return {"error": "busy"}
        try:
            self._reading = ReadingProgress()
            with self._db:
                scores = library.open_file(self._conn, Path(path), progress=self._reading)
            return {"scores": scores}
        except (ScoreImportError, ToolNotFoundError, AudiverisError,
                ReadingCancelled) as error:
            return {"error": error.code}
        except Exception:
            log.exception("Lecture impossible : %s", path)
            return {"error": "unexpected"}
        finally:
            self._reading = None
            self._busy.release()

    def get_progress(self) -> dict:
        """Où en est la lecture en cours : {"stage", "page", "pages", "fraction" (0 à 1),
        "elapsed" (secondes), "cancelling"} ; {"stage": None} s'il n'y en a pas."""
        reading = self._reading
        return reading.to_dict() if reading else {"stage": None}

    def cancel_reading(self) -> dict:
        """Bouton « Annuler » : demande l'arrêt de la lecture en cours."""
        reading = self._reading
        if reading is not None:
            reading.cancel()
        return {"cancelling": reading is not None}

    def list_scores(self) -> list[dict]:
        """Partitions déjà lues, de la plus récente à la plus ancienne."""
        with self._db:
            return library.list_scores(self._conn)

    # --- Vue côte à côte -------------------------------------------------------------------

    def get_page(self, score_id: int, page: int) -> dict:
        """Image d'une page et ses mesures (voir library.page_view)."""
        result = self._guarded(lambda: library.page_view(self._conn, score_id, page))
        return result if result is not None else {"error": "page_not_found"}

    def get_rendering(self, score_id: int) -> dict:
        """Partition reconnue en MEI, pour Verovio (voir library.rendering)."""
        result = self._guarded(lambda: library.rendering(self._conn, score_id))
        return result if result is not None else {"error": "score_not_found"}

    # --- Édition manuelle ------------------------------------------------------------------

    def get_measure(self, score_id: int, measure_id: str) -> dict:
        """Contenu d'une mesure pour l'éditeur (voir editing.measure_details)."""
        def details():
            model = load_model(self._conn, score_id)
            if model is None:
                raise editing.EditError(f"Partition n° {score_id} introuvable.")
            result = editing.measure_details(model, measure_id)
            result["can_undo"] = bool(editing.last_edit(self._conn, score_id))
            return result
        return self._guarded(details)

    def edit_score(self, score_id: int, edit: dict) -> dict:
        """Applique un geste d'édition (voir editing.apply_edit)."""
        return self._guarded(
            lambda: editing.apply_edit(self._conn, self._corrections, score_id, edit))

    def undo_edit(self, score_id: int) -> dict:
        """Annule la dernière modification manuelle : {"measure_id": mesure concernée}."""
        def undo():
            measure_id = editing.undo_last_edit(self._conn, self._corrections, score_id)
            if measure_id is None:
                raise editing.EditError("Aucune modification à annuler.")
            return {"measure_id": measure_id}
        return self._guarded(undo)

    # --- Instruments et transposition ------------------------------------------------------

    def get_instruments(self) -> list[dict]:
        """Table des instruments, pour les choix de l'interface."""
        return instruments.table_for_interface()

    def get_score_instrument(self, score_id: int) -> dict:
        """Instrument et version d'une partition (choisis, ou reconnus d'après son nom)."""
        def read():
            model = load_model(self._conn, score_id)
            if model is None:
                raise instruments.TranspositionError(f"Partition n° {score_id} introuvable.")
            return instruments.instrument_of(model)
        return self._guarded(read)

    def set_score_instrument(self, score_id: int, instrument_id: str, variant_id: str) -> dict:
        """L'utilisateur corrige l'instrument de la partie."""
        return self._guarded(
            lambda: instruments.set_instrument(self._conn, score_id, instrument_id, variant_id))

    def check_transposition(self, score_id: int, request: dict) -> dict:
        """Ce que donnerait une transposition (voir instruments.parts)."""
        return self._guarded(lambda: instruments.check(self._conn, score_id, request))

    def transpose_score(self, score_id: int, request: dict) -> dict:
        """Crée la partition transposée : {"score": résumé, "report": compte rendu}."""
        return self._guarded(lambda: instruments.transpose_score(self._conn, score_id, request))

    # --- Règles apprises ------------------------------------------------------------------

    def get_rules(self) -> list[dict]:
        """Règles apprises des réponses de l'utilisateur (voir learning.rules)."""
        with self._db:
            return [rule.to_dict() for rule in rules.learned_rules(self._conn)]

    def set_rule_enabled(self, key: str, enabled: bool) -> dict:
        """Active ou désactive une règle apprise ; renvoie la liste à jour."""
        def update():
            rules.set_enabled(self._conn, key, bool(enabled))
            return {"rules": [rule.to_dict() for rule in rules.learned_rules(self._conn)]}
        return self._guarded(update)

    # --- Conducteurs -----------------------------------------------------------------------

    def extract_parts(self, score_id: int) -> dict:
        """Une partition par instrument du conducteur : {"scores": [résumés]}."""
        def extract():
            scores = library.extract_parts(self._conn, score_id)
            if not scores:
                raise LibraryError("not_a_conductor")
            return {"scores": scores}
        return self._guarded(extract)

    def get_piece_scores(self, score_id: int) -> list[dict]:
        """Partitions du même morceau (pour choisir celles d'un conducteur)."""
        with self._db:
            return library.piece_scores(self._conn, score_id)

    def assemble_conductor(self, score_ids: list[int]) -> dict:
        """Conducteur fait de ces partitions : {"score": résumé}."""
        def assemble():
            result = library.assemble_conductor(self._conn, [int(i) for i in score_ids])
            if result is None:
                raise LibraryError("conductor_needs_parts")
            return {"score": result}
        return self._guarded(assemble)

    # --- Packs d'apprentissage -------------------------------------------------------------

    def choose_pack_file(self, save: bool, filter_label: str, default_name: str = "") -> str | None:
        """Fenêtre « Enregistrer sous » (save) ou « Ouvrir » pour un pack ; renvoie le
        fichier choisi, ou None."""
        if self._window is None:
            return None
        import webview

        file_types = file_filter(filter_label, [packs.EXTENSION])
        if save:
            chosen = self._window.create_file_dialog(
                webview.FileDialog.SAVE, save_filename=default_name + packs.EXTENSION,
                file_types=file_types)
        else:
            chosen = self._window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=False, file_types=file_types)
        if not chosen:
            return None
        return str(chosen[0] if isinstance(chosen, list | tuple) else chosen)

    def export_pack(self, path: str, author: str = "", include_scores: bool = True) -> dict:
        """Écrit un pack d'apprentissage : {"path", "answers", "scores"}."""
        return self._guarded(
            lambda: packs.export_pack(self._conn, path, author, bool(include_scores)))

    def import_pack(self, path: str) -> dict:
        """Importe un pack reçu d'un autre membre : son résumé, ou {"error": code}."""
        return self._guarded(lambda: packs.import_pack(self._conn, path))

    def list_packs(self) -> list[dict]:
        """Packs importés."""
        with self._db:
            return packs.list_packs(self._conn)

    def remove_pack(self, pack_id: int) -> dict:
        """Retire un pack ; renvoie la liste à jour."""
        def remove():
            packs.remove_pack(self._conn, pack_id)
            return {"packs": packs.list_packs(self._conn)}
        return self._guarded(remove)

    # --- Exports --------------------------------------------------------------------------

    def get_export_options(self, score_id: int) -> dict:
        """Ce que l'interface montre avant d'exporter : nom de fichier proposé, MuseScore
        présent ou non, doutes encore ouverts (questions et passages à vérifier)."""
        def options():
            model = load_model(self._conn, score_id)
            if model is None:
                raise exports.ExportError("score_not_found")
            state = self._questions.state(score_id)
            return {"default_name": exports.default_name(model),
                    "musescore": find_musescore() is not None,
                    "questions": len(state["questions"]), "checks": state["unasked"]}
        return self._guarded(options)

    def choose_save_path(self, filter_label: str, default_name: str, fmt: str) -> str | None:
        """Fenêtre « Enregistrer sous » du système ; renvoie le fichier choisi (ou None)."""
        if self._window is None or fmt not in exports.FORMATS:
            return None
        import webview

        extension = exports.FORMATS[fmt]
        chosen = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=default_name + extension,
            file_types=file_filter(filter_label, [extension]))
        if not chosen:
            return None
        return str(chosen[0] if isinstance(chosen, list | tuple) else chosen)

    def export_score(self, score_id: int, fmt: str, path: str) -> dict:
        """Écrit la partition : {"path", "format", "fallback"} (voir export.files)."""
        return self._guarded(lambda: exports.export_score(self._conn, score_id, fmt, path))

    # --- Questions ------------------------------------------------------------------------

    def get_questions(self, score_id: int) -> dict:
        """Questions encore à poser pour une partition (voir QuestionSession.state)."""
        return self._guarded(lambda: self._questions.state(score_id))

    def answer_question(self, score_id: int, key: str, choice_id: str,
                        value: int | None = None) -> dict:
        """Enregistre une réponse ; renvoie les questions restantes."""
        return self._guarded(lambda: self._questions.answer(score_id, key, choice_id, value))

    def undo_answer(self, score_id: int) -> dict:
        """Annule la dernière réponse ; renvoie les questions (celle-ci reposée)."""
        return self._guarded(lambda: self._questions.undo(score_id))

    # --- Interne --------------------------------------------------------------------------

    def _stop_reading(self, timeout: float = 10.0) -> bool:
        """À la fermeture de la fenêtre : annule la lecture en cours et attend qu'elle
        s'arrête (au plus `timeout` secondes). Renvoie True si plus rien ne tourne.
        Privé (nom en « _ ») : l'interface ne peut pas l'appeler."""
        self.cancel_reading()
        if not self._busy.acquire(timeout=timeout):
            return False
        self._busy.release()
        return True

    def _guarded(self, action) -> dict:
        """Exécute une demande (une à la fois sur la base) ; une erreur devient
        {"error": code}."""
        try:
            with self._db:
                return action()
        except (QuestionError, CorrectionError):
            log.exception("Question impossible")
            return {"error": "question_failed"}
        except editing.EditError as error:
            log.exception("Modification impossible")
            return {"error": error.code}
        except instruments.TranspositionError:
            log.exception("Transposition impossible")
            return {"error": "transposition_failed"}
        except exports.ExportError as error:
            log.exception("Export impossible")
            return {"error": error.code}
        except packs.PackError as error:
            log.exception("Pack impossible")
            return {"error": error.code}
        except LibraryError as error:
            return {"error": error.code}
        except OSError:
            log.exception("Fichier impossible à écrire")
            return {"error": "write_failed"}
        except Exception:
            log.exception("Erreur inattendue")
            return {"error": "unexpected"}
