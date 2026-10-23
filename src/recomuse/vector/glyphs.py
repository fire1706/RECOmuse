"""Signification des caractères des polices de musique.

Les logiciels de gravure écrivent les symboles musicaux comme des lettres d'une police
spéciale : la tête de note noire est le caractère n° 0xCF, la clé de sol le n° 0x26 (« & »)...
Finale (Maestro, Petrucci, Jazz, Engraver, Broadway Copyist) et Sibelius (Opus, Inkpen,
Reprise...) utilisent tous la même table, héritée de la police Sonata d'Adobe.
Les codes ci-dessous ont été vérifiés un par un sur le corpus.

Le PDF ne donne pas directement ce code : selon la façon dont la police est intégrée,
le caractère arrive sous forme de lettre Mac Roman (0xB7 → « ∑ »), de lettre Windows,
ou dans la zone privée Unicode (0xF0CF). glyph_code() ramène tout au code d'origine.

Point d'ancrage (« origine ») de chaque caractère, mesuré sur le corpus :
- tête de note : son centre (donc exactement sur sa ligne ou son interligne) ;
- clé de sol : la 2ᵉ ligne (sol) ; clé de fa : la 4ᵉ ligne (fa) ; clé d'ut : sa ligne d'ut ;
- silences : la ligne du milieu ; chiffres d'indication de mesure : positions 6 et 2.
"""

from dataclasses import dataclass
from typing import Literal

SymbolKind = Literal[
    "clef", "notehead", "rest", "accidental", "time", "flag", "dot", "articulation",
    "dynamic", "multirest", "repeat", "navigation", "tremolo",
]


@dataclass(frozen=True)
class SymbolDef:
    """Ce que représente un caractère de police de musique."""

    kind: SymbolKind
    name: str


# Table des codes (police de type Sonata). Les codes absents sont ignorés.
SONATA_SYMBOLS: dict[int, SymbolDef] = {
    # Clés
    0x26: SymbolDef("clef", "treble"),        # &
    0x3F: SymbolDef("clef", "bass"),          # ?
    0x42: SymbolDef("clef", "c"),             # B : clé d'ut (ut 3 ou ut 4 selon sa ligne)
    0x56: SymbolDef("clef", "treble_8vb"),    # V : clé de sol octaviée (ténor)
    0x2F: SymbolDef("clef", "percussion"),    # / (Sibelius)
    0x8B: SymbolDef("clef", "percussion"),    # (Finale)
    0xE3: SymbolDef("clef", "percussion"),    # (Finale, Maestro)
    0xD6: SymbolDef("clef", "percussion"),    # (Finale, Jazz : petit rectangle)
    # Têtes de notes
    0xCF: SymbolDef("notehead", "black"),     # Ï : noire, croche...
    0xFA: SymbolDef("notehead", "half"),      # ú : blanche
    0x77: SymbolDef("notehead", "whole"),     # w : ronde
    0x57: SymbolDef("notehead", "breve"),     # W : carrée
    0xC0: SymbolDef("notehead", "x"),         # ¿ : croix (percussions, notes « fantômes »)
    0xD5: SymbolDef("notehead", "slash"),     # barre oblique rythmique
    # Silences
    0xB7: SymbolDef("rest", "whole"),         # ∑ : pause
    0xEE: SymbolDef("rest", "half"),          # Ó : demi-pause
    0xCE: SymbolDef("rest", "quarter"),       # Œ : soupir
    0xE4: SymbolDef("rest", "eighth"),        # ‰ : demi-soupir
    0xC5: SymbolDef("rest", "16th"),          # ≈ : quart de soupir
    0xA8: SymbolDef("rest", "32nd"),          # ® : huitième de soupir
    0xF4: SymbolDef("rest", "64th"),
    # Altérations
    0x23: SymbolDef("accidental", "sharp"),   # #
    0x62: SymbolDef("accidental", "flat"),    # b
    0x6E: SymbolDef("accidental", "natural"), # n
    0xDC: SymbolDef("accidental", "double_sharp"),
    0xBA: SymbolDef("accidental", "double_flat"),
    # Indications de mesure (les chiffres sont traités à part : voir TIME_DIGITS)
    0x63: SymbolDef("time", "common"),        # c : 4/4
    0x43: SymbolDef("time", "cut"),           # C : 2/2
    # Crochets
    0x6A: SymbolDef("flag", "eighth_up"),     # j
    0x4A: SymbolDef("flag", "eighth_down"),   # J
    0x72: SymbolDef("flag", "16th_up"),       # r
    0x52: SymbolDef("flag", "16th_down"),     # R
    # Point (de prolongation ou staccato : distingués à la tâche 4b-2)
    0x2E: SymbolDef("dot", "dot"),
    # Articulations
    0x3E: SymbolDef("articulation", "accent"),     # >
    0x5E: SymbolDef("articulation", "marcato"),    # ^
    0x76: SymbolDef("articulation", "marcato"),    # v (sous la note)
    0x2D: SymbolDef("articulation", "tenuto"),     # -
    0x55: SymbolDef("articulation", "fermata"),    # U
    0x75: SymbolDef("articulation", "fermata"),    # u (sous la note)
    0x2B: SymbolDef("articulation", "stopped"),    # + (cuivres bouchés)
    # Nuances
    0x70: SymbolDef("dynamic", "p"),
    0x66: SymbolDef("dynamic", "f"),
    0x46: SymbolDef("dynamic", "mf"),
    0x50: SymbolDef("dynamic", "mp"),
    0xC4: SymbolDef("dynamic", "ff"),
    0xB9: SymbolDef("dynamic", "pp"),
    0xA7: SymbolDef("dynamic", "sfz"),
    # Divers
    0xF6: SymbolDef("multirest", "hbar"),     # barre de pause multiple (police Jazz)
    0xD4: SymbolDef("repeat", "measure"),     # répétition de la mesure précédente
    0xDE: SymbolDef("navigation", "coda"),
    0x25: SymbolDef("navigation", "segno"),
    0xBE: SymbolDef("tremolo", "tremolo"),
}

# Chiffres des indications de mesure (et des nolets ou pauses multiples s'ils sont
# au-dessus de la portée) : codes 0x30 à 0x39 = « 0 » à « 9 ».
TIME_DIGITS = {code: code - 0x30 for code in range(0x30, 0x3A)}

# Fonction d'une police de musique, d'après son nom.
FontRole = Literal["symbols", "text", "percussion", "special"]

# Mots qui signalent une police de LETTRES de la même famille (titres, accords, paroles).
_TEXT_FONT_MARKS = ("text", "script", "cord", "chord")


def font_role(base_name: str) -> FontRole:
    """Rôle d'une police de musique : symboles, texte, percussions ou symboles spéciaux."""
    lowered = base_name.lower().replace(" ", "")
    if any(mark in lowered for mark in _TEXT_FONT_MARKS):
        return "text"
    if "perc" in lowered:
        return "percussion"
    if "special" in lowered:
        return "special"
    return "symbols"


def glyph_code(char: str, pdf_encoding: str = "") -> int | None:
    """Code d'origine (0 à 255) d'un caractère de police de musique, ou None.

    Le PDF peut décoder les octets de la police selon la table Mac (« ∑ » = 0xB7) ou
    Windows (« Ï » = 0xCF), et un même fichier peut contenir deux copies d'une police
    avec chacune sa table. Plutôt que de deviner la table, on essaie les deux et on garde
    le code qui correspond à un symbole connu : une seule des deux lectures en donne un
    (par ex. « œ » vaut 0xCF, tête de note, chez Mac, mais 0x9C, rien, chez Windows).
    `pdf_encoding` (« MacRomanEncoding », « WinAnsiEncoding ») ne sert qu'à départager.
    """
    codepoint = ord(char)
    if 0xF000 <= codepoint <= 0xF0FF:  # zone privée des polices « symbole » Windows
        return codepoint & 0xFF
    if codepoint < 0x80:
        return codepoint
    order = ["cp1252", "mac_roman"] if "WinAnsi" in pdf_encoding else ["mac_roman", "cp1252"]
    codes = []
    for encoding in order:
        try:
            codes.append(char.encode(encoding)[0])
        except UnicodeEncodeError:
            continue
    known = [code for code in codes if code in SONATA_SYMBOLS]
    if known:
        return known[0]
    return codes[0] if codes else None
