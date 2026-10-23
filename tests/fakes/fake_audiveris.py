"""Faux Audiveris pour les tests : imite sa ligne de commande, son journal et ses fichiers.

Comportement choisi par la variable d'environnement FAKE_AUDIVERIS_MODE :
- « ok » (par défaut) : deux mouvements, sur les feuilles 1 et 2 ;
- « fail »  : s'arrête avec le code 1 ;
- « hang »  : ne finit jamais (pour tester le délai maximal) ;
- « empty » : se termine sans produire de MusicXML.
Le nombre de feuilles est lu dans FAKE_AUDIVERIS_SHEETS (2 par défaut).
"""

import os
import sys
import time
import zipfile
from pathlib import Path

STEPS = ["LOAD", "BINARY", "SCALE", "GRID", "HEADERS", "STEM_SEEDS", "BEAMS", "LEDGERS",
         "HEADS", "STEMS", "REDUCTION", "CUE_BEAMS", "TEXTS", "MEASURES", "CHORDS", "CURVES",
         "SYMBOLS", "LINKS", "RHYTHMS", "PAGE"]

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container><rootfiles><rootfile full-path="{name}.xml"/></rootfiles></container>"""

SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <identification>
    <miscellaneous><miscellaneous-field name="source-sheet-{sheet}">1 2</miscellaneous-field>
    </miscellaneous>
  </identification>
  <credit page="1"><credit-words default-x="600" default-y="1600" font-size="24">Marche de test</credit-words></credit>
  <part-list><score-part id="P1"><part-name>Flute</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1"><attributes><time><beats>2</beats><beat-type>4</beat-type></time></attributes>
      <direction><direction-type><words>Allegro</words></direction-type></direction></measure>
    <measure number="2"/>
  </part>
</score-partwise>"""


def write_mxl(path: Path, sheet: int) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER.format(name=path.stem))
        archive.writestr(f"{path.stem}.xml", SCORE.format(sheet=sheet))


def main() -> int:
    args = sys.argv[1:]
    output_dir = Path(args[args.index("-output") + 1])
    book = Path(args[args.index("--") + 1])
    mode = os.environ.get("FAKE_AUDIVERIS_MODE", "ok")
    sheets = int(os.environ.get("FAKE_AUDIVERIS_SHEETS", "2"))
    # Les arguments reçus, pour que les tests puissent les vérifier.
    (output_dir / "fake-args.txt").write_text("\n".join(args), encoding="utf-8")

    if mode == "hang":
        time.sleep(600)
    for sheet in range(1, sheets + 1):
        for step in STEPS:
            print(f"INFO  [{book.stem}#{sheet}]   StepMonitoring 98   | {step}", flush=True)
    (output_dir / f"{book.stem}-20261023T1200.log").write_text("journal", encoding="utf-8")
    if mode == "fail":
        return 1
    (output_dir / f"{book.stem}.omr").write_bytes(b"omr")
    if mode != "empty":
        for sheet in range(1, sheets + 1):
            write_mxl(output_dir / f"{book.stem}.mvt{sheet}.mxl", sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
