"""Recherche des programmes externes : Audiveris, Tesseract et ses fichiers de langues.

Ordre de recherche pour chaque programme :
1. variable d'environnement (RECOMUSE_AUDIVERIS, RECOMUSE_TESSERACT, RECOMUSE_TESSDATA) ;
2. copie livrée avec l'application installée (dossier « tools » de PyInstaller, tâche 15) ;
3. emplacements d'installation habituels du système ;
4. programmes accessibles par le PATH.

Fichiers de langues (tessdata) : RECOmuse utilise son propre dossier, partagé avec
Audiveris (qui le reçoit par la variable TESSDATA_PREFIX). Il faut la version « tessdata »
standard : les versions « best » et « fast » n'ont pas le moteur classique qu'Audiveris
utilise pour reconnaître les polices (gras, italique).
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from recomuse import paths

# Langues des textes des partitions de la fanfare (codes Tesseract).
OCR_LANGUAGES = ("fra", "nld", "eng", "deu")

# Nom du sous-dossier des fichiers de langues dans les données locales.
TESSDATA_DIRNAME = "tessdata"


class ToolNotFoundError(RuntimeError):
    """Un programme externe indispensable est introuvable.

    `code` est traduit par l'interface : « audiveris_not_found », « tesseract_not_found »
    ou « tessdata_not_found ».
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _bundled_tools_dir() -> Path | None:
    """Dossier des outils livrés avec l'application installée (None en développement)."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root) / "tools" if bundle_root else None


def _first_existing(candidates: list[Path | None]) -> Path | None:
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    return None


def _from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _which(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def find_audiveris() -> Path | None:
    """Chemin du programme Audiveris, ou None s'il est introuvable."""
    bundled = _bundled_tools_dir()
    candidates: list[Path | None] = [_from_env("RECOMUSE_AUDIVERIS")]
    if sys.platform == "win32":
        candidates += [
            bundled / "Audiveris" / "Audiveris.exe" if bundled else None,
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Audiveris"
            / "Audiveris.exe",
        ]
    elif sys.platform == "darwin":
        candidates += [
            bundled / "Audiveris.app" / "Contents" / "MacOS" / "Audiveris" if bundled else None,
            Path("/Applications/Audiveris.app/Contents/MacOS/Audiveris"),
        ]
    else:
        candidates += [Path("/opt/audiveris/bin/Audiveris")]
    candidates.append(_which("Audiveris") or _which("audiveris"))
    return _first_existing(candidates)


def find_tesseract() -> Path | None:
    """Chemin du programme Tesseract, ou None s'il est introuvable."""
    bundled = _bundled_tools_dir()
    candidates: list[Path | None] = [_from_env("RECOMUSE_TESSERACT")]
    if sys.platform == "win32":
        exe = Path("Tesseract-OCR") / "tesseract.exe"
        candidates += [
            bundled / exe if bundled else None,
            # Installation pour l'utilisateur seul (winget) ou pour toute la machine.
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / exe,
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / exe,
        ]
    elif sys.platform == "darwin":
        candidates += [
            bundled / "tesseract" / "bin" / "tesseract" if bundled else None,
            Path("/opt/homebrew/bin/tesseract"),  # Homebrew, puces Apple
            Path("/usr/local/bin/tesseract"),     # Homebrew, puces Intel
        ]
    candidates.append(_which("tesseract"))
    return _first_existing(candidates)


def find_tessdata() -> Path | None:
    """Dossier des fichiers de langues, ou None s'il n'en contient aucun."""
    bundled = _bundled_tools_dir()
    candidates = [
        _from_env("RECOMUSE_TESSDATA"),
        bundled / TESSDATA_DIRNAME if bundled else None,
        paths.data_dir() / TESSDATA_DIRNAME,
        _from_env("TESSDATA_PREFIX"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    return None


def installed_languages(tessdata: Path) -> list[str]:
    """Codes des langues présentes dans un dossier tessdata (ex. ['deu', 'eng'])."""
    return sorted(p.stem for p in tessdata.glob("*.traineddata"))


@dataclass(frozen=True)
class ToolsStatus:
    """État des programmes externes, affiché par l'interface (écran de diagnostic)."""

    audiveris: Path | None
    tesseract: Path | None
    tessdata: Path | None
    languages: list[str]
    missing_languages: list[str]

    @property
    def ready(self) -> bool:
        """Vrai si tout est là pour reconnaître une partition avec ses textes."""
        return bool(self.audiveris and self.tesseract and self.tessdata
                    and not self.missing_languages)

    def to_dict(self) -> dict:
        return {
            "audiveris": str(self.audiveris) if self.audiveris else None,
            "tesseract": str(self.tesseract) if self.tesseract else None,
            "tessdata": str(self.tessdata) if self.tessdata else None,
            "languages": self.languages,
            "missing_languages": self.missing_languages,
            "ready": self.ready,
        }


def check_tools() -> ToolsStatus:
    """Vérifie la présence de tous les programmes externes."""
    tessdata = find_tessdata()
    languages = installed_languages(tessdata) if tessdata else []
    return ToolsStatus(
        audiveris=find_audiveris(),
        tesseract=find_tesseract(),
        tessdata=tessdata,
        languages=languages,
        missing_languages=[lang for lang in OCR_LANGUAGES if lang not in languages],
    )


def require(path: Path | None, code: str) -> Path:
    """Renvoie le chemin, ou lève ToolNotFoundError(code) s'il est absent."""
    if path is None:
        raise ToolNotFoundError(code)
    return path


def ocr_language_spec(tessdata: Path) -> str:
    """Langues à utiliser, au format Tesseract « fra+nld+eng+deu » (seulement les présentes)."""
    available = installed_languages(tessdata)
    return "+".join(lang for lang in OCR_LANGUAGES if lang in available)
