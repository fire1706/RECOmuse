"""Progression d'une lecture de partition, et son annulation.

Lire une grosse partition prend plusieurs minutes. Le moteur note où il en est (étape,
page en cours, part du travail déjà faite) dans un objet ReadingProgress, que
l'interface lit régulièrement (Api.get_progress) pour sa barre de progression. Le bouton
« Annuler » demande l'arrêt (Api.cancel_reading) : le moteur s'arrête au prochain point
de contrôle (à chaque page, et tout de suite pour Audiveris, dont le programme est arrêté).

Part du travail faite : chaque étape a un poids proche de son temps réel (une page lue
par Audiveris prend une trentaine de secondes, une page préparée une demi-seconde), pour
que la barre avance à peu près régulièrement et que le temps restant ait un sens.
Tant que la préparation des pages n'est pas finie, on ne sait pas encore lesquelles sont
scannées : on compte au pire (toutes passeront par Audiveris), puis le plan est corrigé ;
la barre peut alors faire un bond en avant, jamais en arrière.
"""

import threading
import time

# Étapes annoncées à l'interface (traduites par elle), dans l'ordre.
STAGES = ("import", "vector", "texts", "audiveris", "model", "done")

# Durée approximative, en secondes, d'une unité de travail de chaque étape :
# une page (import, vector, texts, model) ou une étape d'Audiveris sur une feuille.
SECONDS_PER_UNIT = {
    "import": 0.5,
    "vector": 1.0,
    "texts": 1.5,
    "audiveris": 1.5,   # 20 étapes par feuille : une trentaine de secondes par page
    "model": 0.3,
}

# Nombre d'étapes d'Audiveris par feuille (voir recognition/audiveris.py, AUDIVERIS_STEPS).
AUDIVERIS_STEPS_PER_SHEET = 20


class ReadingCancelled(RuntimeError):
    """L'utilisateur a annulé la lecture (code « cancelled », traduit par l'interface)."""

    code = "cancelled"


class ReadingProgress:
    """Où en est une lecture. Écrit par le moteur, lu par l'interface (autre fil
    d'exécution) : les lectures et écritures passent par un verrou."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.started = time.monotonic()
        self.stage = "import"
        self.page: int | None = None       # page en cours (à partir de 1) dans l'étape
        self.pages: int | None = None      # nombre de pages de l'étape
        self._planned: dict[str, int] = {}  # étape → unités de travail prévues
        self._done: dict[str, int] = {}     # étape → unités faites
        self._fraction = 0.0

    # --- Écrit par le moteur ------------------------------------------------------------

    def plan(self, **units: int) -> None:
        """Annonce (ou corrige) le travail prévu : plan(vector=3, audiveris=40, ...)."""
        with self._lock:
            self._planned.update(units)
            self._recompute()

    def update(self, stage: str, done: int, total: int | None = None,
               page: int | None = None, pages: int | None = None) -> None:
        """Note l'avancée d'une étape : `done` unités faites (sur `total`, qui corrige le
        plan s'il est donné). Lève ReadingCancelled si l'annulation a été demandée."""
        self.check()
        with self._lock:
            self.stage = stage
            if total is not None:
                self._planned[stage] = total
            self._done[stage] = done
            self.page, self.pages = page, pages
            self._recompute()

    def check(self) -> None:
        """Point de contrôle : lève ReadingCancelled si l'annulation a été demandée."""
        if self._cancel.is_set():
            raise ReadingCancelled()

    def finish(self) -> None:
        with self._lock:
            self.stage, self.page, self.pages = "done", None, None
            self._fraction = 1.0

    # --- Demandé par l'interface --------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def cancel_event(self) -> threading.Event:
        """Pour Audiveris, qui doit être arrêté pendant qu'il travaille."""
        return self._cancel

    def to_dict(self) -> dict:
        """État pour l'interface : étape, page, part faite (0 à 1), secondes écoulées."""
        with self._lock:
            return {"stage": self.stage, "page": self.page, "pages": self.pages,
                    "fraction": round(self._fraction, 4),
                    "elapsed": round(time.monotonic() - self.started, 1),
                    "cancelling": self._cancel.is_set()}

    # --- Interne ------------------------------------------------------------------------

    def _recompute(self) -> None:
        """Part faite = temps estimé des unités faites / temps estimé de tout le plan.
        Jamais en recul : un plan corrigé à la baisse ne fait qu'avancer la barre."""
        total = sum(n * SECONDS_PER_UNIT.get(s, 1.0) for s, n in self._planned.items())
        done = sum(min(n, self._planned.get(s, n)) * SECONDS_PER_UNIT.get(s, 1.0)
                   for s, n in self._done.items())
        if total > 0:
            self._fraction = max(self._fraction, min(done / total, 0.99))
