"""Tests des briques de la lecture vectorielle : codes des caractères, hauteurs des notes."""

import pytest

from recomuse.vector import pitch
from recomuse.vector.glyphs import SONATA_SYMBOLS, font_role, glyph_code

# --- Codes des caractères ----------------------------------------------------------------


@pytest.mark.parametrize(("char", "encoding", "expected"), [
    ("", "", 0xCF),                 # zone privée Unicode (Sibelius, Opus / Inkpen)
    ("&", "MacRomanEncoding", 0x26),      # ASCII : identique partout
    ("∑", "MacRomanEncoding", 0xB7),      # pause, table Mac
    ("œ", "MacRomanEncoding", 0xCF),      # tête noire, table Mac
    ("Ï", "WinAnsiEncoding", 0xCF),       # tête noire, table Windows
    ("ú", "", 0xFA),                      # tête blanche, table Windows
    ("˙", "", 0xFA),                      # tête blanche, table Mac
    ("‰", "WinAnsiEncoding", 0xE4),       # demi-soupir : seule la table Mac donne un symbole
])
def test_glyph_code(char, encoding, expected):
    assert glyph_code(char, encoding) == expected


def test_glyph_code_prefers_a_known_symbol():
    """« ú » vaut 0xFA (tête blanche) chez Windows et 0x9C (rien) chez Mac."""
    assert glyph_code("ú", "MacRomanEncoding") == 0xFA


def test_known_codes():
    assert SONATA_SYMBOLS[0xCF].name == "black"
    assert SONATA_SYMBOLS[0x26].kind == "clef"
    assert SONATA_SYMBOLS[0xB7].name == "whole"


@pytest.mark.parametrize(("name", "role"), [
    ("Maestro", "symbols"), ("Jazz", "symbols"), ("Opus", "symbols"),
    ("JazzText", "text"), ("Inkpen2Script", "text"), ("JazzCord", "text"),
    ("MaestroPercussion", "percussion"), ("OpusSpecial", "special"),
])
def test_font_role(name, role):
    assert font_role(name) == role


# --- Hauteurs ----------------------------------------------------------------------------


@pytest.mark.parametrize(("clef", "clef_position", "position", "expected"), [
    ("treble", 2, 0, ("E", 4)),     # ligne du bas en clé de sol : mi4
    ("treble", 2, 8, ("F", 5)),     # ligne du haut : fa5
    ("treble", 2, -2, ("C", 4)),    # 1re ligne supplémentaire en dessous : do4
    ("treble", 2, 12, ("C", 6)),    # 2e ligne supplémentaire au-dessus : do6
    ("bass", 6, 0, ("G", 2)),       # ligne du bas en clé de fa : sol2
    ("bass", 6, 8, ("A", 3)),
    ("c", 4, 4, ("C", 4)),          # clé d'ut 3 : do4 sur la ligne du milieu
    ("c", 6, 6, ("C", 4)),          # clé d'ut 4
    ("treble_8vb", 2, 0, ("E", 3)),
])
def test_pitch_at(clef, clef_position, position, expected):
    assert pitch.pitch_at(clef, clef_position, position) == expected


@pytest.mark.parametrize(("fifths", "step", "alter"), [
    (0, "F", 0), (1, "F", 1), (1, "C", 0), (4, "D", 1), (7, "B", 1),
    (-1, "B", -1), (-1, "E", 0), (-3, "A", -1), (-3, "D", 0),
])
def test_key_alter(fifths, step, alter):
    assert pitch.key_alter(fifths, step) == alter


def test_pitch_name():
    assert pitch.pitch_name("F", 4, 1) == "F#4"
    assert pitch.pitch_name("B", 3, -1) == "Bb3"
    assert pitch.pitch_name("C", 5, 0) == "C5"
