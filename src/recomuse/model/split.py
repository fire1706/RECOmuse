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


def normalized(text: str | None) -> str | None:
    """Texte simplifié pour comparer deux noms : minuscules, sans accents ni ponctuation."""
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
    words = (normalized(name) or "").split()
    title_words = set((normalized(title) or "").split())
    key = tuple(w[:-1] if len(w) > 3 and w.endswith("s") else w
                for w in words if w not in title_words and w not in GENERIC_WORDS)
    return key or None


def _same_title(a: str | None, b: str | None) -> bool:
    a, b = normalized(a), normalized(b)
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


# Identifiant d'une mesure lue par Audiveris : a<mouvement>.<partie>.<rang>.
_AUDIVERIS_MEASURE = re.compile(r"a(\d+)\.\d+\.(\d+)")


def _single_staff(model: ScoreModel, start: int, end: int | None
                  ) -> tuple[Part, list[Measure]] | None:
    """Partie à une portée dont Audiveris a réparti les systèmes entre plusieurs parties
    (vu sur Amina : le piccolo est la partie 1 sur certains systèmes, la partie 2 sur
    d'autres). Dans un mouvement d'Audiveris, les parties ont les mêmes mesures dans le
    même ordre (vides là où elles ne sont pas imprimées) ; l'identifiant d'une mesure le
    dit : « a3.1.12 » = mouvement 3, partie 1, 12e mesure. Si sur ces pages une seule
    partie au plus est imprimée à chaque mesure, on les réunit en une portée, avec à
    chaque mesure celle qui est imprimée. Renvoie (portée réunie, ses mesures sur ces
    pages), ou None (une seule partie, mesures qui ne viennent pas d'Audiveris, ou
    plusieurs portées imprimées ensemble : conducteur, piano...)."""
    if len(model.parts) < 2:
        return None
    columns: dict[tuple[int, int], list[Measure]] = {}
    for part in model.parts:
        for measure in part.measures:
            match = _AUDIVERIS_MEASURE.fullmatch(measure.id)
            if match is None:
                return None
            columns.setdefault((int(match[1]), int(match[2])), []).append(measure)
    whole, kept = [], []
    for _, column in sorted(columns.items()):
        placed = [m for m in column if m.bbox is not None]
        here = [m for m in placed if _within(m.page, start, end)]
        if len(here) > 1:
            return None
        whole.append(placed[0] if len(placed) == 1 else column[0])
        if here:
            kept.append(here[0])
    if not kept:
        return None
    return Part(id=model.parts[0].id, name=model.parts[0].name, measures=whole), kept


def _printed_staves(staves: list[tuple[Part, list[Measure]]]) -> list[tuple[Part, list[Measure]]]:
    """Portées (et leurs mesures) vraiment imprimées sur une tranche de pages.

    Audiveris ne reconnaît pas toujours le même instrument d'une page à l'autre : sur un
    PDF de 89 pages de parties séparées, il en a fait 234 parties, chacune avec TOUTES les
    mesures du livre, vides là où elle n'est pas imprimée. On ne garde que les portées dont
    au moins une mesure est placée sur la page ; si aucune ne l'est (lecture sans
    positions), toutes celles qui ont des mesures."""
    with_measures = [(part, kept) for part, kept in staves if kept]
    printed = [(part, kept) for part, kept in with_measures
               if any(m.bbox is not None for m in kept)]
    return printed or with_measures


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
        merged = _single_staff(model, start, end)
        if merged is not None:
            staves = [merged]
        else:
            staves = _printed_staves(
                [(part, [m for m in part.measures if _within(m.page, start, end)])
                 for part in model.parts])
        part_model = ScoreModel(
            title=model.title or header.title, composers=list(model.composers),
            instrument=instrument, tempo=header.tempo or (model.tempo if index == 0 else None),
            source_path=model.source_path,
            parts=[Part(id=f"P{rank + 1}", name=instrument,
                        measures=_with_initial_state(part.measures, kept))
                   for rank, (part, kept) in enumerate(staves)],
            pages=[p for p in model.pages if _within(p.number, start, end)],
        )
        part_model.renumber()
        result.append(part_model)
    return result
