"""Pont entre l'interface React et le moteur Python.

pywebview rend chaque méthode publique de la classe Api appelable depuis le
JavaScript de l'interface :  await window.pywebview.api.get_app_info()
Il n'y a pas de serveur HTTP pour l'API : les appels passent directement par pywebview.
Chaque appel s'exécute dans son propre fil d'exécution : l'interface peut demander où en
est la lecture d'un fichier (get_progress) pendant que open_file travaille.

Règles :
- les méthodes renvoient des données simples (dict, list, str, nombres) que
  pywebview convertit en JSON pour l'interface ;
- les textes affichés à l'utilisateur ne sont PAS construits ici : l'interface
  les traduit elle-même (français / anglais) à partir de codes ;
- une erreur est renvoyée sous la forme {"error": code}, jamais comme une exception.
"""

import logging
import platform
import sqlite3
import sys
import threading
from pathlib import Path

from recomuse import __version__, library
from recomuse.importer import ScoreImportError
from recomuse.importer.loading import IMAGE_EXTENSIONS
from recomuse.learning.corrections import CorrectionError
from recomuse.learning.journal import CorrectionJournal
from recomuse.questions.session import QuestionError, QuestionSession
from recomuse.recognition.audiveris import AudiverisError
from recomuse.recognition.tools import ToolNotFoundError

log = logging.getLogger(__name__)

# Extensions proposées dans la fenêtre « Ouvrir ».
OPEN_EXTENSIONS = (".pdf", *sorted(IMAGE_EXTENSIONS))


class Api:
    """Fonctions du moteur exposées à l'interface."""

    def __init__(self, conn: sqlite3.Connection, db_path: str) -> None:
        # Attributs « privés » (préfixe _) : pywebview n'expose pas ce qui commence par _.
        self._conn = conn
        self._db_path = db_path
        self._journal = CorrectionJournal(conn)
        self._questions = QuestionSession(conn)
        self._window = None                 # fenêtre pywebview, donnée par app.py
        self._progress: str | None = None   # étape de la lecture en cours (library.STAGES)
        self._busy = threading.Lock()       # une seule lecture de fichier à la fois

    def ping(self) -> str:
        """Vérifie que le pont fonctionne : renvoie toujours « pong »."""
        return "pong"

    def get_app_info(self) -> dict:
        """Informations affichées dans l'écran d'accueil de l'interface."""
        return {
            "version": __version__,
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "database_path": self._db_path,
            "correction_count": self._journal.count(),
        }

    # --- Partitions -----------------------------------------------------------------------

    def choose_file(self, filter_label: str) -> str | None:
        """Ouvre la fenêtre « Ouvrir » du système ; renvoie le fichier choisi (ou None).
        `filter_label` : nom du filtre de fichiers, traduit par l'interface."""
        if self._window is None:
            return None
        # Importé ici seulement : les tests n'ouvrent pas de fenêtre.
        import webview

        patterns = ";".join(f"*{ext}" for ext in OPEN_EXTENSIONS)
        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False,
            file_types=(f"{filter_label} ({patterns})",))
        return str(chosen[0]) if chosen else None

    def open_file(self, path: str) -> dict:
        """Lit un fichier : {"scores": [une partition par partie]} ou {"error": code}."""
        if not self._busy.acquire(blocking=False):
            return {"error": "busy"}
        try:
            self._progress = "import"
            scores = library.open_file(self._conn, Path(path), progress=self._set_progress)
            return {"scores": scores}
        except (ScoreImportError, ToolNotFoundError, AudiverisError) as error:
            return {"error": error.code}
        except Exception:
            log.exception("Lecture impossible : %s", path)
            return {"error": "unexpected"}
        finally:
            self._progress = None
            self._busy.release()

    def get_progress(self) -> dict:
        """Étape de la lecture en cours (None : aucune lecture)."""
        return {"stage": self._progress}

    def list_scores(self) -> list[dict]:
        """Partitions déjà lues, de la plus récente à la plus ancienne."""
        return library.list_scores(self._conn)

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

    def _set_progress(self, stage: str) -> None:
        self._progress = stage

    def _guarded(self, action) -> dict:
        """Exécute une demande ; une erreur devient {"error": code}."""
        try:
            return action()
        except (QuestionError, CorrectionError):
            log.exception("Question impossible")
            return {"error": "question_failed"}
        except Exception:
            log.exception("Erreur inattendue")
            return {"error": "unexpected"}
