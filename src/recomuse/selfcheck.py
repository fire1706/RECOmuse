"""Diagnostic du logiciel installé : « RECOmuse.exe --check [partition.pdf] ».

Vérifie, sans ouvrir de fenêtre, que RECOmuse trouve tout ce qu'il lui faut : l'interface,
Audiveris, Tesseract et ses langues (embarqués dans l'installation, ou installés sur la
machine), MuseScore (facultatif). Avec une partition, la lit de bout en bout (import,
reconnaissance, modèle, questions, export MusicXML) dans un dossier temporaire.

Le résultat est écrit dans self-check.json, dans le dossier des données (l'application
installée n'a pas de console), et affiché s'il y en a une. Utile pour l'aide à distance :
le membre envoie ce fichier.
"""

import json
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

from recomuse import __version__, paths
from recomuse.export.musescore import find_musescore
from recomuse.recognition import tools

# Nom du fichier du diagnostic, dans le dossier des données.
REPORT_FILENAME = "self-check.json"


def _where(path: Path | None) -> dict:
    """Chemin d'un outil, et s'il vient de l'installation de RECOmuse elle-même."""
    bundled = tools._bundled_tools_dir()
    inside = bool(path and bundled and bundled in path.parents)
    return {"path": str(path) if path else None, "bundled": inside}


def run(score: Path | None = None) -> dict:
    """Fait le diagnostic ; renvoie le rapport (aussi écrit dans self-check.json)."""
    status = tools.check_tools()
    report: dict = {
        "version": __version__,
        "python": platform.python_version(),
        "platform": sys.platform,
        "installed": getattr(sys, "frozen", False),
        "ui": (paths.ui_dist_dir() / "index.html").is_file(),
        "audiveris": _where(status.audiveris),
        "tesseract": _where(status.tesseract),
        "tessdata": _where(status.tessdata),
        "languages": status.languages,
        "missing_languages": status.missing_languages,
        "musescore": str(find_musescore()) if find_musescore() else None,
    }
    if score is not None:
        report["score"] = _read(Path(score))
    report["ok"] = (report["ui"] and status.audiveris is not None
                    and status.tesseract is not None and not status.missing_languages
                    and report.get("score", {}).get("error") is None)
    out = paths.data_dir() / REPORT_FILENAME
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    report["report_path"] = str(out)
    return report


def _read(score: Path) -> dict:
    """Lit une partition de bout en bout, dans une base et un dossier temporaires."""
    # Importés ici : le diagnostic des outils doit marcher même si ces modules échouent.
    from recomuse import library
    from recomuse.export import files as exports
    from recomuse.questions.session import QuestionSession
    from recomuse.storage import database

    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="recomuse-check-") as folder:
            work = Path(folder)
            conn = database.connect(work / "check.sqlite3")
            try:
                scores = library.open_file(conn, score, work_root=work / "imports")
                session = QuestionSession(conn, work_dir=work / "validation")
                result = []
                for summary in scores:
                    state = session.state(summary["score_id"])
                    written = exports.export_score(conn, summary["score_id"], "musicxml",
                                                   work / "export")
                    result.append({"instrument": summary["instrument"],
                                   "measures": summary["measure_count"],
                                   "questions": len(state["questions"]),
                                   "exported": Path(written["path"]).is_file()})
            finally:
                conn.close()
        return {"file": score.name, "seconds": round(time.perf_counter() - start),
                "parts": result, "error": None}
    except Exception as error:  # noqa: BLE001 (le diagnostic rapporte toute erreur)
        return {"file": score.name, "seconds": round(time.perf_counter() - start),
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc()[-2000:]}
