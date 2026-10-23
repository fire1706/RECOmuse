"""Emplacements des fichiers sur la machine de l'utilisateur.

Les données locales (base SQLite, extraits d'images) sont rangées dans le dossier
prévu par le système pour les données d'application :
- Windows : %LOCALAPPDATA%\\RECOmuse
- macOS   : ~/Library/Application Support/RECOmuse
- autres  : ~/.local/share/RECOmuse

La variable d'environnement RECOMUSE_DATA_DIR permet d'imposer un autre dossier
(utile pour les tests, ou pour une installation portable).
"""

import os
import sys
from pathlib import Path

APP_NAME = "RECOmuse"

# Nom du fichier de la base de données locale.
DATABASE_FILENAME = "recomuse.sqlite3"

# Nom du sous-dossier qui contient les extraits d'images des symboles.
SNIPPETS_DIRNAME = "snippets"


def data_dir() -> Path:
    """Renvoie le dossier des données locales et le crée s'il n'existe pas encore."""
    override = os.environ.get("RECOMUSE_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        base = root / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_NAME

    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    """Chemin complet du fichier de la base SQLite."""
    return data_dir() / DATABASE_FILENAME


def snippets_dir() -> Path:
    """Dossier des extraits d'images (créé s'il n'existe pas encore)."""
    path = data_dir() / SNIPPETS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def ui_dist_dir() -> Path:
    """Dossier de l'interface React compilée (résultat de « npm run build »).

    En développement, il se trouve dans ui/dist à la racine du dépôt.
    Dans l'application installée par PyInstaller, il est copié à côté du programme
    (sys._MEIPASS est le dossier temporaire où PyInstaller décompresse ses fichiers).
    """
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "ui"
    # src/recomuse/paths.py -> remonter de trois niveaux pour atteindre la racine du dépôt.
    return Path(__file__).resolve().parents[2] / "ui" / "dist"
