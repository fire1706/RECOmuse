"""Fabrique l'installateur Windows de RECOmuse, de bout en bout.

Étapes :
1. interface : « npm run build » dans ui/ ;
2. outils embarqués : Audiveris, Tesseract et ses langues copiés dans build/tools ;
3. PyInstaller : le programme et tout ce qu'il lui faut dans dist/RECOmuse ;
4. Inno Setup : dist/RECOmuse-<version>-installation.exe.

Prérequis sur la machine de construction : Node.js, PyInstaller (dans le .venv),
Inno Setup 6, Audiveris, Tesseract et ses langues (voir le README).

Usage (à la racine du dépôt) :  .venv\\Scripts\\python packaging\\build_windows.py
"""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as file:
        return tomllib.load(file)["project"]["version"]


def find_iscc() -> Path:
    """Compilateur d'Inno Setup (installation pour tous, ou pour l'utilisateur seul)."""
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6",
    ]
    found = shutil.which("ISCC") or next(
        (str(c / "ISCC.exe") for c in candidates if (c / "ISCC.exe").is_file()), None)
    if found is None:
        raise SystemExit("Inno Setup 6 est introuvable (winget install JRSoftware.InnoSetup).")
    return Path(found)


def run(command: list[str], cwd: Path = ROOT) -> None:
    print(">", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, shell=command[0] == "npm")


def main() -> None:
    if not (ROOT / "LICENSE").is_file():
        print("ATTENTION : pas de fichier LICENSE (texte de l'AGPL-3.0) à la racine ; "
              "il doit accompagner le logiciel distribué.")
    run(["npm", "run", "build"], cwd=ROOT / "ui")
    run([sys.executable, str(ROOT / "packaging" / "prepare_tools.py"),
         str(ROOT / "build" / "tools")])
    run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "recomuse.spec"),
         "--noconfirm", "--distpath", str(ROOT / "dist"),
         "--workpath", str(ROOT / "build" / "pyinstaller")])
    run([str(find_iscc()), f"/DAppVersion={version()}", str(ROOT / "packaging" / "recomuse.iss")])
    installer = ROOT / "dist" / f"RECOmuse-{version()}-installation.exe"
    print(f"Installateur : {installer} ({installer.stat().st_size / 1e6:.0f} Mo)")


if __name__ == "__main__":
    main()
