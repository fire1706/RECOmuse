"""Séparation des parties d'un même PDF.

Beaucoup de fichiers contiennent toutes les parties d'un morceau à la suite (flûte, puis
clarinette, puis...). Le modèle construit en lit une seule « partie » qui enchaîne tout :
il faut la couper aux débuts de parties.

Une page commence une nouvelle partie si son en-tête nomme un AUTRE instrument que la
partie en cours (les pages suivantes d'une partie répètent souvent le même nom, ou n'en
ont pas), ou si elle nomme un instrument, reprend le titre du morceau et s'ouvre sur un
chiffrage sans numéro de mesure (comme toute première page de partie).
Une partie peut avoir plusieurs portées (piano) : chaque tranche de pages garde toutes ses
portées. Un conducteur ne nomme pas un nouvel instrument à chaque page : il n'est pas coupé.
"""

import re
import unicodedata
from dataclasses import replace

from recomuse.model.score import Measure, Part, ScoreModel, Symbol
from recomuse.recognition.header import HeaderInfo


def _normalized(text: str | None) -> str | None:
    if not text:
        return None
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    words = re.findall(r"[a-z0-9]+", plain)
    return " ".join(words) or None


# Mots qui ne distinguent pas un instrument d'un autre (« Drum Set » = « Drums »).
GENERIC_WORDS = {"set", "in", "part", "partie", "stimme", "solo"}


def instrument_key(name: str | None, title: str | None = None) -> tuple[str, ...] | None:
    """Clé d'un nom d'instrument pour savoir si deux en-têtes désignent la même partie :
    sans les mots du titre (en-tête courant « Guitar Throwin' Down »), sans mots génériques,
    au singulier. Les numéros restent : « Trumpet 1 » ≠ « Trumpet 2 »."""
    words = (_normalized(name) or "").split()
    title_words = set((_normalized(title) or "").split())
    key = tuple(w[:-1] if len(w) > 3 and w.endswith("s") else w
                for w in words if w not in title_words and w not in GENERIC_WORDS)
    return key or None


def _same_title(a: str | None, b: str | None) -> bool:
    a, b = _normalized(a), _normalized(b)
    return bool(a and b and (a == b or a in b or b in a))


def part_starts(model: ScoreModel, page_headers: dict[int, HeaderInfo]) -> list[int]:
    """Pages où commence une partie (la première page de musique en fait toujours partie)."""
    if not model.parts:
        return []
    measures = model.parts[0].measures   # la portée du haut est présente sur toutes les pages
    pages = sorted({m.page for m in measures if m.page is not None})
    starts: list[int] = []
    current: tuple[str, ...] | None = None
    for page in pages:
        header = page_headers.get(page) or HeaderInfo()
        instrument = instrument_key(header.instrument, model.title)
        first = next(m for m in measures if m.page == page)
        opens_part = (any(s.kind == "time" for s in first.attributes)
                      and first.printed_number is None
                      and _same_title(header.title, model.title))
        other_instrument = bool(instrument and current and instrument != current)
        if not starts or other_instrument or (instrument and opens_part):
            starts.append(page)
        if instrument:
            current = instrument
    return starts


def _within(page: int | None, start: int, end: int | None) -> bool:
    """Vrai si la page fait partie de la tranche [start, end[ (end None : jusqu'à la fin)."""
    return page is not None and page >= start and (end is None or page < end)


# Réglages qui restent en vigueur d'une mesure à l'autre (dans cet ordre en début de partie).
STATE_KINDS = ("clef", "key", "time")


def _state_before(measures: list[Measure], first: Measure) -> dict[str, Symbol]:
    """Clé, armure et chiffrage en vigueur juste avant la mesure `first`."""
    state: dict[str, Symbol] = {}
    for measure in measures:
        if measure is first:
            break
        for symbol in measure.attributes:
            if symbol.kind in STATE_KINDS:
                state[symbol.kind] = symbol
    return state


def _with_initial_state(measures: list[Measure], kept: list[Measure]) -> list[Measure]:
    """La lecture n'écrit une clé, une armure ou un chiffrage que lorsqu'ils changent : la
    partie suivante du PDF en hérite sans les répéter. Une partie séparée doit les avoir
    dans sa première mesure : on y recopie ceux qui manquent."""
    first = kept[0]
    present = {s.kind for s in first.attributes}
    missing = [symbol for kind, symbol in _state_before(measures, first).items()
               if kind not in present]
    if missing:
        copies = [replace(symbol, id=f"{first.id}.{symbol.kind}0", page=first.page,
                          bbox=first.bbox) for symbol in missing]
        ordered = sorted(copies + first.attributes,
                         key=lambda s: STATE_KINDS.index(s.kind) if s.kind in STATE_KINDS
                         else len(STATE_KINDS))
        kept[0] = replace(first, attributes=ordered)
    return kept


def split_parts(model: ScoreModel, page_headers: dict[int, HeaderInfo]) -> list[ScoreModel]:
    """Un modèle par partie trouvée dans le PDF (le modèle lui-même s'il n'y en a qu'une)."""
    starts = part_starts(model, page_headers)
    if len(starts) <= 1:
        return [model]
    result = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else None
        header = page_headers.get(start) or HeaderInfo()
        instrument = header.instrument or (model.instrument if index == 0 else None)
        part_model = ScoreModel(
            title=model.title or header.title, composers=list(model.composers),
            instrument=instrument, tempo=header.tempo or (model.tempo if index == 0 else None),
            source_path=model.source_path,
            parts=[Part(id=f"P{rank + 1}", name=instrument,
                        measures=_with_initial_state(part.measures, kept))
                   for rank, (part, kept) in enumerate(
                       (part, [m for m in part.measures if _within(m.page, start, end)])
                       for part in model.parts)
                   if kept],
            pages=[p for p in model.pages if _within(p.number, start, end)],
        )
        part_model.renumber()
        result.append(part_model)
    return result
