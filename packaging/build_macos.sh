#!/bin/sh
# Fabrique l'application macOS de RECOmuse (RECOmuse.app dans un .dmg), sur un Mac.
#
# Utilisé par le workflow GitHub Actions .github/workflows/build-macos.yml (puces Apple et
# Intel), et utilisable à la main sur un Mac (à la racine du dépôt) :
#     sh packaging/build_macos.sh
#
# Prérequis : Python 3.12 (avec le .venv du projet et PyInstaller), Node.js, Homebrew,
# et l'outil « gh » (GitHub) connecté, pour télécharger Audiveris.
# L'application n'est pas signée : au premier lancement, clic droit → Ouvrir.
set -eu

AUDIVERIS_VERSION="${AUDIVERIS_VERSION:-5.11.0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/build/tools"
VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
ARCH="$(uname -m)"
cd "$ROOT"

echo "== Interface"
(cd ui && npm ci && npm run build)

echo "== Outils embarqués"
rm -rf "$TOOLS" && mkdir -p "$TOOLS/tessdata"

# Audiveris : l'application (avec son Java) tirée de son image disque officielle.
# Le nom du fichier dépend de la version et de la puce : à vérifier si le
# téléchargement échoue (https://github.com/Audiveris/audiveris/releases).
mkdir -p build/download
case "$ARCH" in arm64) PATTERN="*macosx*arm64*.dmg" ;; *) PATTERN="*macosx*x86_64*.dmg" ;; esac
gh release download "$AUDIVERIS_VERSION" --repo Audiveris/audiveris --pattern "$PATTERN" \
    --dir build/download --clobber
DMG="$(ls build/download/*.dmg | head -n 1)"
MOUNT="$(mktemp -d)"
hdiutil attach "$DMG" -nobrowse -mountpoint "$MOUNT"
cp -R "$MOUNT/Audiveris.app" "$TOOLS/Audiveris.app"
hdiutil detach "$MOUNT"

# Tesseract : le programme de Homebrew, avec ses bibliothèques copiées à côté de lui.
brew install tesseract dylibbundler
mkdir -p "$TOOLS/tesseract/bin" "$TOOLS/tesseract/lib"
cp "$(brew --prefix tesseract)/bin/tesseract" "$TOOLS/tesseract/bin/"
dylibbundler -of -b -x "$TOOLS/tesseract/bin/tesseract" -d "$TOOLS/tesseract/lib" \
    -p @executable_path/../lib

# Langues de Tesseract : la version « tessdata » standard (celle qu'Audiveris sait lire).
for LANG in fra nld eng deu osd; do
    curl -fsSL -o "$TOOLS/tessdata/$LANG.traineddata" \
        "https://github.com/tesseract-ocr/tessdata/raw/main/$LANG.traineddata"
done

echo "== PyInstaller"
python3 -m PyInstaller packaging/recomuse.spec --noconfirm --distpath dist \
    --workpath build/pyinstaller

echo "== Image disque"
DMG_OUT="dist/RECOmuse-$VERSION-macos-$ARCH.dmg"
rm -f "$DMG_OUT"
hdiutil create -volname RECOmuse -srcfolder dist/RECOmuse.app -ov -format UDZO "$DMG_OUT"
echo "Application : $DMG_OUT"
