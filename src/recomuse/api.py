"""Pont entre l'interface React et le moteur Python.

pywebview rend chaque méthode publique de la classe Api appelable depuis le
JavaScript de l'interface :  await window.pywebview.api.get_app_info()
Il n'y a pas de serveur HTTP pour l'API : les appels passent directement par pywebview.

Règles :
- les méthodes renvoient des données simples (dict, list, str, nombres) que
  pywebview convertit en JSON pour l'interface ;
- les textes affichés à l'utilisateur ne sont PAS construits ici : l'interface
  les traduit elle-même (français / anglais) à partir de codes.
"""

import platform
import sqlite3
import sys

from recomuse import __version__
from recomuse.learning.journal import CorrectionJournal


class Api:
    """Fonctions du moteur exposées à l'interface."""

    def __init__(self, conn: sqlite3.Connection, db_path: str) -> None:
        # Attributs « privés » (préfixe _) : pywebview n'expose pas ce qui commence par _.
        self._conn = conn
        self._db_path = db_path
        self._journal = CorrectionJournal(conn)

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
