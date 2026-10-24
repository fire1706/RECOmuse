"""Point d'entrée du logiciel : ouvre la fenêtre pywebview qui affiche l'interface React.

Deux modes :
- normal  : affiche l'interface compilée (ui/dist, produite par « npm run build ») ;
- --dev   : affiche le serveur de développement Vite (« npm run dev » dans ui/),
            qui recharge l'interface à chaque modification du code.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from recomuse import paths
from recomuse.api import Api
from recomuse.storage import database

WINDOW_TITLE = "RECOmuse"

# Fichier du journal, dans le dossier des données (paths.data_dir).
LOG_FILENAME = "recomuse.log"

# Adresse du serveur de développement Vite (voir ui/vite.config.ts).
DEV_SERVER_URL = "http://localhost:5173"

# Page affichée si l'interface n'a pas encore été compilée.
# (Message technique destiné au développeur, pas à l'utilisateur final : l'installateur
# contient toujours l'interface compilée.)
MISSING_UI_HTML = """
<!doctype html>
<html lang="fr"><body style="font-family: sans-serif; padding: 2em">
<h1>Interface introuvable / Interface not found</h1>
<p>Compilez l'interface : <code>cd ui</code> puis <code>npm run build</code>.</p>
<p>Build the interface: <code>cd ui</code> then <code>npm run build</code>.</p>
</body></html>
"""


def resolve_ui_entry(dev: bool, dist_dir: Path | None = None) -> tuple[str | None, str | None]:
    """Détermine ce que la fenêtre doit afficher.

    Renvoie (url, html) : exactement l'un des deux est rempli.
    - url  : adresse ou chemin de fichier à ouvrir ;
    - html : contenu HTML de secours si l'interface compilée est absente.
    """
    if dev:
        return DEV_SERVER_URL, None

    index = (dist_dir or paths.ui_dist_dir()) / "index.html"
    if index.is_file():
        return str(index), None
    return None, MISSING_UI_HTML


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="recomuse", description="RECOmuse")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="affiche le serveur de développement Vite et active les outils de débogage",
    )
    parser.add_argument(
        "--check",
        nargs="?",
        const="",
        metavar="PARTITION",
        help="diagnostic sans fenêtre (outils trouvés ; lecture complète d'une partition)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Lance le logiciel."""
    # Importé ici et non en haut du fichier : les tests peuvent ainsi utiliser
    # ce module sans ouvrir de fenêtre ni dépendre de l'affichage.
    import webview

    args = parse_args(argv)
    # Journal du logiciel (erreurs inattendues...) : l'application installée n'a pas de
    # console, il est donc écrit dans un fichier du dossier des données.
    logging.basicConfig(filename=paths.data_dir() / LOG_FILENAME, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s : %(message)s",
                        encoding="utf-8")

    if args.check is not None:
        # Diagnostic : pas de fenêtre ; le rapport va dans self-check.json.
        from recomuse import selfcheck

        report = selfcheck.run(Path(args.check) if args.check else None)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        sys.exit(0 if report["ok"] else 1)

    db_path = paths.database_path()
    conn = database.connect(db_path)
    api = Api(conn, str(db_path))

    url, html = resolve_ui_entry(args.dev)
    window = webview.create_window(
        WINDOW_TITLE,
        url=url,
        html=html,
        js_api=api,
        width=1400,
        height=900,
        min_size=(900, 600),
    )
    api._window = window   # pour la fenêtre « Ouvrir » (Api.choose_file)
    try:
        # Bloque jusqu'à la fermeture de la fenêtre.
        # Pour un fichier local, pywebview le sert lui-même depuis 127.0.0.1 (fichiers
        # statiques de l'interface uniquement) : les navigateurs intégrés refusent de
        # charger des modules JavaScript directement depuis le disque (file://).
        webview.start(debug=args.dev)
    finally:
        # Fenêtre fermée pendant une lecture : Audiveris est arrêté, sinon il continuerait
        # à travailler en arrière-plan, pour rien.
        api._stop_reading()
        conn.close()


if __name__ == "__main__":
    main()
