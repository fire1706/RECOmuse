"""Export MuseScore (.mscz) : RECOmuse écrit le MusicXML, MuseScore le convertit.

MuseScore est installé chez la plupart des membres de la fanfare. Il est appelé en ligne
de commande (« MuseScore4 -o partie.mscz partie.musicxml ») : la conversion prend quelques
secondes, sans ouvrir de fenêtre. S'il est absent, l'interface propose le MusicXML, que
MuseScore (ou un autre logiciel) ouvrira plus tard.

Ordre de recherche : variable RECOMUSE_MUSESCORE, emplacements d'installation habituels
(MuseScore 4, puis 3), programmes accessibles par le PATH.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Une conversion qui dure plus longtemps a sans doute bloqué.
TIMEOUT_SECONDS = 180


class MuseScoreError(RuntimeError):
    """La conversion par MuseScore a échoué ; `code` est traduit par l'interface."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def find_musescore() -> Path | None:
    """Chemin du programme MuseScore, ou None s'il est introuvable."""
    candidates: list[Path | None] = []
    value = os.environ.get("RECOMUSE_MUSESCORE")
    if value:
        candidates.append(Path(value))
    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates += [program_files / "MuseScore 4" / "bin" / "MuseScore4.exe",
                       program_files / "MuseScore 3" / "bin" / "MuseScore3.exe"]
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore"),
                       Path("/Applications/MuseScore 3.app/Contents/MacOS/mscore")]
    for name in ("MuseScore4", "mscore4portable", "mscore", "musescore", "MuseScore3"):
        found = shutil.which(name)
        candidates.append(Path(found) if found else None)
    return next((c for c in candidates if c and c.is_file()), None)


def convert(executable: Path, musicxml: str, out_path: Path) -> Path:
    """Fait écrire `out_path` (.mscz, ou tout format que MuseScore connaît : .pdf, .mid)
    par MuseScore à partir du texte MusicXML."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recomuse-") as folder:
        source = Path(folder) / "partition.musicxml"
        source.write_text(musicxml, encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(executable), "-o", str(out_path), str(source)],
                capture_output=True, timeout=TIMEOUT_SECONDS, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise MuseScoreError("musescore_timeout") from None
        except OSError as error:
            raise MuseScoreError("musescore_failed", str(error)) from None
    if completed.returncode != 0 or not out_path.is_file():
        detail = (completed.stderr or b"").decode("utf-8", "replace")[-500:]
        raise MuseScoreError("musescore_failed", detail)
    return out_path
