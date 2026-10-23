"""Analyse de l'en-tête d'une partie : titre, instrument, tempo, compositeur / arrangeur.

Règles simples, fondées sur la mise en page habituelle d'une partie de fanfare :
- l'INSTRUMENT contient un nom d'instrument connu (« Solo Bb Cornet », « Alto Sax 1 ») ;
- le TEMPO contient un mot de tempo ou une indication métronomique (« Allegretto », « ♩ = 120 ») ;
- le COMPOSITEUR / ARRANGEUR est écrit à droite, ou annoncé par « arr. », « bearb. »... ;
- le TITRE est le texte nettement le plus grand ; sinon le plus grand texte restant,
  de préférence centré.

Ce ne sont que des propositions : en cas de doute, RECOmuse posera la question
(tâche 8). Les listes de mots couvrent le français, le néerlandais, l'anglais et l'allemand.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from recomuse.recognition.musicxml import CreditText
from recomuse.recognition.ocr import OcrLine
from recomuse.vector.primitives import TextLine

# Noms d'instruments (sans accents, en minuscules). Un mot de la ligne doit COMMENCER par
# l'un d'eux : « clarinet » reconnaît aussi « clarinette » et « clarinetten ».
# La table complète des instruments viendra à la tâche 10.
INSTRUMENT_WORDS = (
    # bois
    "piccolo", "flute", "fluit", "flote", "hautbois", "oboe", "hobo", "clarinet", "klarinet",
    "basson", "bassoon", "fagot", "sax", "saxofoon",
    # cuivres
    "cornet", "kornet", "bugle", "flugelhorn", "bugel", "trompet", "trumpet", "hoorn",
    "trombone", "posaune", "euphonium", "bariton", "baryton", "saxhorn", "tenorhorn",
    "tuba", "contrebasse", "basse",
    # percussions et autres
    "percussion", "slagwerk", "schlagzeug", "drum", "batterie", "timbales", "timpani",
    "pauken", "glockenspiel", "xylophone", "mallets", "keyboard", "piano", "guitar", "guitare",
    # voix
    "vocal", "voice", "voix", "chant", "zang", "gesang",
    # conducteur
    "conductor", "conducteur", "direction", "directie", "partitur",
)

# Noms courts qui doivent être des mots ENTIERS (sinon « cor » reconnaîtrait « corps »).
INSTRUMENT_EXACT_WORDS = ("cor", "cors", "horn", "horns", "horner", "bass", "bas", "score")

# Mots de tempo et de caractère (sans accents, en minuscules), ou leur début.
TEMPO_WORDS = (
    "grave", "largo", "lento", "adagio", "andante", "andantino", "moderato", "modto", "mod",
    "allegretto", "allegro", "vivace", "presto", "maestoso", "marcia", "marziale", "tempo",
    "rubato", "con moto", "swing", "ballad", "rock", "latin", "march", "marche", "marsch",
    "mars", "langsam", "lebhaft", "massig", "lent", "vif", "rapide", "modere", "rustig", "snel",
)

# Indication métronomique : « = 120 », « =120 », « ♩ = 96 ».
METRONOME = re.compile(r"=\s*c?a?\.?\s*\d{2,3}\b")

# Mots qui annoncent un compositeur ou un arrangeur (mots entiers).
# « Music » n'en fait pas partie : il commence aussi des titres (« Music from The Incredibles ») ;
# « Music by X » est reconnu grâce à « by ».
COMPOSER_MARKERS = (
    "arr", "arranged", "arrangement", "bearb", "bewerking", "bew", "transcr", "orch",
    "by", "von", "door", "composed",
)

# Part minimale de la largeur de la page à partir de laquelle un texte est « à droite ».
RIGHT_SIDE = 0.55

# Un texte au moins 1,3 fois plus haut que tous les autres est forcément le titre.
TITLE_SIZE_RATIO = 1.3


@dataclass
class HeaderInfo:
    """Ce que l'en-tête semble indiquer (chaque champ peut rester vide)."""

    title: str | None = None
    instrument: str | None = None
    tempo: str | None = None
    composers: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    """Minuscules sans accents : « Flöte » → « flote », « Modéré » → « modere »."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def words_of(text: str) -> list[str]:
    return re.findall(r"[a-z]+", normalize(text))


def is_noise(text: str) -> bool:
    """Vrai pour les « lignes » qui sont en fait des bouts de symboles (« A-€* », « X s »).

    Il faut au moins un mot de deux lettres, et une majorité de lettres.
    """
    visible = [c for c in text if not c.isspace()]
    letters = [c for c in visible if c.isalpha()]
    has_word = any(len(word) >= 2 for word in re.findall(r"[^\W\d_]+", text))
    return not has_word or len(letters) / len(visible) < 0.5


def is_instrument(text: str) -> bool:
    return any(
        word.startswith(INSTRUMENT_WORDS) or word in INSTRUMENT_EXACT_WORDS
        for word in words_of(text)
    )


def is_tempo(text: str) -> bool:
    if METRONOME.search(text):
        return True
    normalized = normalize(text)
    words = words_of(text)
    return any(
        (" " in tempo and tempo in normalized) or any(w.startswith(tempo) for w in words)
        for tempo in TEMPO_WORDS
        # Les mots très courts (« mod », « mars ») doivent être des mots entiers.
        if len(tempo) > 4 or tempo in words
    )


def is_composer(text: str) -> bool:
    return any(word in COMPOSER_MARKERS for word in words_of(text))


def _clean(text: str) -> str:
    """Retire la ponctuation parasite en début et fin : « Solo Bb Cornet. » → « Solo Bb Cornet ».

    Les parenthèses ne sont retirées que si elles entourent tout le texte
    (« (CONDUCTOR) » → « CONDUCTOR ») ou si elles sont orphelines ; celles de
    « Sarasate (1844 - 1908) » sont gardées.
    """
    junk = " .,;:-_*'\"[]"
    text = text.strip(junk)
    if text.startswith("(") and text.endswith(")") and text.count("(") == 1:
        text = text[1:-1].strip(junk)
    if text.count("(") != text.count(")"):
        text = text.strip(junk + "()")
    return text


def analyze_header(lines: list[OcrLine], page_width: int) -> HeaderInfo:
    """Range les lignes lues dans l'en-tête en titre, instrument, tempo, compositeurs."""
    info = HeaderInfo()
    candidates = [line for line in lines if not is_noise(line.text)]

    # 1. L'instrument : la première ligne qui en contient un nom.
    instrument_line = next((l for l in candidates if is_instrument(l.text)), None)
    if instrument_line:
        info.instrument = _clean(instrument_line.text)
        candidates.remove(instrument_line)

    # 2. Un texte nettement plus grand que tous les autres est le titre, même s'il
    #    ressemble à un tempo (« MARCHE D'ACOZ ») ou est écrit à droite.
    by_height = sorted(candidates, key=lambda l: l.height, reverse=True)
    if by_height and (len(by_height) == 1
                      or by_height[0].height >= TITLE_SIZE_RATIO * by_height[1].height):
        info.title = _clean(by_height[0].text)
        candidates.remove(by_height[0])

    # 3. Le reste : tempo, compositeurs, autres textes.
    remaining: list[OcrLine] = []
    for line in candidates:
        text = _clean(line.text)
        if info.tempo is None and is_tempo(text):
            info.tempo = text
        elif is_composer(text) or line.left > RIGHT_SIDE * page_width:
            info.composers.append(text)
        else:
            remaining.append(line)

    # 4. Sans titre évident : le plus grand texte restant ; à taille égale, le plus centré.
    if info.title is None and remaining:
        center = page_width / 2
        title_line = max(remaining, key=lambda l: (l.height, -abs(l.center_x - center)))
        info.title = _clean(title_line.text)
        remaining.remove(title_line)
    info.other = [_clean(l.text) for l in remaining]
    return info


def complete_with_credits(info: HeaderInfo, credits: list[CreditText]) -> HeaderInfo:
    """Complète les champs restés vides avec les textes lus par Audiveris.

    Audiveris lit aussi l'en-tête (avec Tesseract) mais range moins bien les textes :
    on ne s'en sert qu'en secours.
    """
    candidates = [c for c in credits if not is_noise(c.text)]
    if info.instrument is None:
        info.instrument = next((_clean(c.text) for c in candidates if is_instrument(c.text)), None)
    if info.title is None:
        others = [c for c in candidates if not is_instrument(c.text) and not is_composer(c.text)]
        if others:
            info.title = _clean(max(others, key=lambda c: c.font_size or 0).text)
    return info


def lines_from_pdf_text(texts: list[TextLine], dpi: int = 300) -> list[OcrLine]:
    """Convertit les textes exacts d'une page PDF vectorielle au format des lignes lues par
    Tesseract (pixels à `dpi`), pour les analyser de la même façon."""
    scale = dpi / 72
    return [
        OcrLine(text=t.text, left=round(t.x0 * scale), top=round(t.y0 * scale),
                width=round((t.x1 - t.x0) * scale), height=round((t.y1 - t.y0) * scale),
                confidence=100.0)
        for t in sorted(texts, key=lambda t: (t.y0, t.x0))
    ]
