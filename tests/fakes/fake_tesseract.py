"""Faux Tesseract pour les tests : renvoie toujours le même en-tête au format TSV.

FAKE_TESSERACT_MODE=fail le fait échouer (code 1).
"""

import os
import sys

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"

WORDS = [
    # (bloc, ligne, gauche, haut, largeur, hauteur, confiance, texte)
    (1, 1, 100, 60, 80, 40, 92, "Flûte"),
    (1, 1, 190, 60, 30, 40, 90, "1"),
    (2, 1, 800, 50, 300, 90, 95, "MARCHE"),
    (2, 1, 1120, 50, 200, 90, 94, "D'ACOZ"),
    (3, 1, 1700, 160, 200, 35, 88, "arr."),
    (3, 1, 1910, 160, 260, 35, 87, "J. Dupont"),
    (4, 1, 150, 300, 220, 45, 91, "Allegro"),
]


def main() -> int:
    if os.environ.get("FAKE_TESSERACT_MODE") == "fail":
        print("erreur simulée", file=sys.stderr)
        return 1
    lines = [HEADER]
    for block, line, left, top, width, height, conf, text in WORDS:
        lines.append(f"5\t1\t{block}\t1\t{line}\t1\t{left}\t{top}\t{width}\t{height}\t{conf}\t{text}")
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
