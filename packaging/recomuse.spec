# Recette PyInstaller de RECOmuse (Windows et macOS).
#
# Produit un dossier (« onedir ») : dist/RECOmuse/ sous Windows, dist/RECOmuse.app sous
# macOS. On y trouve, à côté du programme :
# - ui/     : l'interface compilée (« npm run build » dans ui/) ;
# - tools/  : Audiveris, Tesseract et ses langues (packaging/prepare_tools.py, ou le
#             script macOS) ; RECOmuse les y cherche en premier (recognition/tools.py) ;
# - les fichiers de données du moteur (schéma SQL, table des instruments).
#
# Lancement :  pyinstaller packaging/recomuse.spec --noconfirm
# (depuis la racine du dépôt, après avoir préparé ui/dist et build/tools).

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
TOOLS = ROOT / "build" / "tools"
UI = ROOT / "ui" / "dist"
if not (UI / "index.html").is_file():
    raise SystemExit("Interface absente : lancer « npm run build » dans ui/.")
if not TOOLS.is_dir():
    raise SystemExit("Outils absents : lancer packaging/prepare_tools.py.")

datas = [(str(UI), "ui"), (str(TOOLS), "tools")]
datas += collect_data_files("recomuse")

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=collect_submodules("recomuse") + collect_submodules("webview"),
    # pymupdf.layout (analyse de mise en page par un modèle ONNX) n'est pas utilisé et ses
    # fichiers de modèle ne seraient pas copiés : pymupdf s'en passe s'il est absent.
    excludes=["tkinter", "pytest", "ruff", "pymupdf.layout", "onnxruntime"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RECOmuse",
    # Pas de fenêtre noire : le journal va dans recomuse.log. RECOMUSE_CONSOLE=1 donne une
    # version avec console, pour voir une erreur au démarrage.
    console=bool(os.environ.get("RECOMUSE_CONSOLE")),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="RECOmuse")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="RECOmuse.app",
        bundle_identifier="be.fanfare-acoz.recomuse",
        info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"},
    )
