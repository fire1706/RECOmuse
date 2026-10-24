"""Hauteur des notes écrites : clé, position sur la portée, armure et altérations.

On compte en « degrés » : do, ré, mi, fa, sol, la, si (C D E F G A B), et l'octave
suit la notation internationale : do4 (C4) = do du milieu du piano.
Un degré correspond à une position sur la portée (une ligne ou un interligne).

Les hauteurs calculées ici sont ÉCRITES, telles que sur la partie : la transposition
des instruments (une clarinette en si♭ sonne un ton plus bas) vient à la tâche 10.
"""

STEPS = "CDEFGAB"

# Note de référence de chaque clé, à la position de son point d'ancrage :
# clé de sol → sol4 sur sa ligne, clé de fa → fa3, clé d'ut → do4.
CLEF_REFERENCE: dict[str, tuple[str, int]] = {
    "treble": ("G", 4),
    "treble_8vb": ("G", 3),   # clé de sol avec un 8 en dessous (une octave plus bas)
    "bass": ("F", 3),
    "c": ("C", 4),
}

# Position du point d'ancrage de chaque clé dans sa place habituelle
# (0 = ligne du bas) : sert quand aucune clé n'a été vue sur la portée.
DEFAULT_CLEF_POSITION = {"treble": 2, "treble_8vb": 2, "bass": 6, "c": 4}

# Ordre des dièses et des bémols à l'armure.
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"

# Effet de chaque altération, en demi-tons.
ACCIDENTAL_ALTER = {"sharp": 1, "flat": -1, "natural": 0, "double_sharp": 2, "double_flat": -2}


def degree(step: str, octave: int) -> int:
    """Numéro de degré absolu (do0 = 0, ré0 = 1... do4 = 28)."""
    return octave * 7 + STEPS.index(step)


def from_degree(value: int) -> tuple[str, int]:
    return STEPS[value % 7], value // 7


def pitch_at(clef: str, clef_position: int, position: int) -> tuple[str, int]:
    """Note (degré, octave) à la `position` donnée, pour une clé placée à `clef_position`."""
    step, octave = CLEF_REFERENCE[clef]
    return from_degree(degree(step, octave) + position - clef_position)


def clef_bottom_line(clef: dict) -> int:
    """Degré de la note sur la ligne du bas de la portée, pour une clé du modèle
    ({"sign": "G", "line": 2, "octave_change": 0}) : mi4 en clé de sol, sol2 en clé de fa."""
    step, octave = MODEL_CLEF_REFERENCE.get(clef.get("sign"), ("G", 4))
    line = clef.get("line") or 2
    return degree(step, octave) - 2 * (line - 1) + 7 * (clef.get("octave_change") or 0)


def moved_by_clef(value: dict, shift: int, fifths: int) -> dict:
    """Note qui garde sa place sur la portée quand la clé change de `shift` degrés : son
    nouveau nom et son octave. Une note qui suivait l'armure la suit encore (si♭ en sol
    avec 3 bémols → ré en fa... qui prend le bémol de l'armure s'il en a un)."""
    step, octave = from_degree(degree(value["step"], value["octave"]) + shift)
    alter = value.get("alter") or 0
    if alter == key_alter(fifths, value["step"]):
        alter = key_alter(fifths, step)
    return {"step": step, "octave": octave, "alter": alter}


# Clés du modèle (signe MusicXML) → note de référence, sur la ligne de la clé.
MODEL_CLEF_REFERENCE: dict[str, tuple[str, int]] = {"G": ("G", 4), "F": ("F", 3), "C": ("C", 4)}


def key_alter(fifths: int, step: str) -> int:
    """Altération apportée par l'armure : `fifths` > 0 = nombre de dièses, < 0 = de bémols."""
    if fifths > 0 and step in SHARP_ORDER[:fifths]:
        return 1
    if fifths < 0 and step in FLAT_ORDER[:-fifths]:
        return -1
    return 0


def pitch_name(step: str, octave: int, alter: int) -> str:
    """Nom lisible : « C5 », « F#4 », « Bb3 »."""
    sign = {2: "##", 1: "#", 0: "", -1: "b", -2: "bb"}[alter]
    return f"{step}{sign}{octave}"
