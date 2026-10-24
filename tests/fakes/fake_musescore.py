"""Faux MuseScore pour les tests : « fake_musescore.py -o sortie entrée ».

Vérifie que l'entrée est un MusicXML lisible, puis écrit une archive .mscz minimale
(qui contient le MusicXML reçu). FAKE_MUSESCORE_FAIL=1 : échoue comme un vrai plantage.
"""

import os
import sys
import xml.etree.ElementTree as ET
import zipfile

args = sys.argv[1:]
out_path = args[args.index("-o") + 1]
source = args[-1]
if os.environ.get("FAKE_MUSESCORE_FAIL"):
    print("plantage simulé", file=sys.stderr)
    sys.exit(3)
root = ET.parse(source).getroot()
assert root.tag == "score-partwise", root.tag
with zipfile.ZipFile(out_path, "w") as archive:
    archive.write(source, "partition.musicxml")
