"""Modèle interne → MEI, pour l'affichage par Verovio (vue côte à côte).

MEI (Music Encoding Initiative) est le format que Verovio dessine le mieux, et il permet de
donner un identifiant (xml:id) à chaque note : Verovio le garde dans l'image (SVG). Un clic
sur une note du rendu retrouve ainsi le symbole du modèle, et inversement.

Ce MEI sert à l'AFFICHAGE : il reste fidèle au modèle tel qu'il a été lu, erreurs
comprises (une mesure trop longue reste trop longue), pour que le musicien voie ce que le
logiciel a compris. Les ligatures (croches reliées) ne sont pas encore lues : les croches
sont dessinées séparées.

Signes d'expression (model/marks.py) : les articulations sont dans la note ; liaisons,
soufflets, nuances, points d'orgue et tempo sont des « événements de contrôle » MEI, écrits
à la fin de la mesure où ils commencent et rattachés à leurs notes par identifiant (une
liaison peut finir dans une mesure suivante).
"""

import re
from collections import defaultdict
from fractions import Fraction
from xml.sax.saxutils import escape, quoteattr

from recomuse.model import marks
from recomuse.model.score import Measure, Part, ScoreModel, Symbol
from recomuse.vector.pitch import key_alter

# Durée écrite (en noires, sans point ni nolet) → valeur MEI (1 = ronde, 4 = noire...).
MEI_DURATIONS = {Fraction(8): "breve", Fraction(4): "1", Fraction(2): "2", Fraction(1): "4",
                 Fraction(1, 2): "8", Fraction(1, 4): "16", Fraction(1, 8): "32",
                 Fraction(1, 16): "64", Fraction(1, 32): "128"}
# Durée par défaut quand elle manque : d'après la forme de la tête.
HEAD_DURATIONS = {"whole": "1", "half": "2"}
ACCIDENTALS = {-2: "ff", -1: "f", 0: "n", 1: "s", 2: "x"}
CLEF_SHAPES = {"G": "G", "F": "F", "C": "C", "percussion": "perc"}
NCNAME = re.compile(r"[^A-Za-z0-9_.-]")


class _Ids:
    """Identifiants MEI (des noms XML valides) et leur correspondance avec le modèle."""

    def __init__(self) -> None:
        self.symbols: dict[str, str] = {}    # identifiant MEI → identifiant du symbole
        self.measures: dict[str, str] = {}   # identifiant MEI → identifiant de la mesure
        self._used: set[str] = set()
        self._by_symbol: dict[str, str] = {}

    def make(self, prefix: str, raw: str, table: dict[str, str]) -> str:
        base = f"{prefix}-{NCNAME.sub('_', raw)}"
        name, k = base, 1
        while name in self._used:
            k += 1
            name = f"{base}-{k}"
        self._used.add(name)
        table[name] = raw
        return name

    def symbol(self, raw: str) -> str:
        """Identifiant MEI d'un symbole, toujours le même (une liaison qui finit plus loin
        désigne une note pas encore écrite)."""
        if raw not in self._by_symbol:
            self._by_symbol[raw] = self.make("s", raw, self.symbols)
        return self._by_symbol[raw]


def model_to_mei(model: ScoreModel) -> dict:
    """MEI d'une partition, et correspondance des identifiants :
    {"mei": texte, "symbols": {id MEI: id du symbole}, "measures": {id MEI: id de mesure}}.

    Les portées dessinées : la première partie, et celles qui ont autant de mesures qu'elle
    (les deux portées d'un piano). Une portée qui n'existe que sur certaines lignes n'est
    pas dessinée."""
    ids = _Ids()
    parts = [p for p in model.parts if p.measures]
    parts = [p for p in parts if len(p.measures) == len(parts[0].measures)] if parts else []
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="4.0.1">',
             "<meiHead><fileDesc><titleStmt>",
             f"<title>{escape(model.title or '')}</title>",
             "</titleStmt><pubStmt/></fileDesc></meiHead>",
             "<music><body><mdiv><score>"]
    lines.append(_score_def(model, parts))
    lines.append("<section>")
    states = [_State.at_start(part) for part in parts]
    controls = _control_events(model, parts, ids)
    for rank in range(len(parts[0].measures) if parts else 0):
        measures = [part.measures[rank] for part in parts]
        lines += _changes(measures, states)
        lines.append(_measure(measures, states, ids, controls.get(rank, [])))
    lines += ["</section>", "</score></mdiv></body></music>", "</mei>"]
    return {"mei": "\n".join(lines), "symbols": ids.symbols, "measures": ids.measures}


class _State:
    """Clé, armure et chiffrage en vigueur sur une portée."""

    def __init__(self) -> None:
        self.clef: dict | None = None
        self.fifths = 0
        self.time: tuple[int, int] | None = None

    @classmethod
    def at_start(cls, part: Part) -> "_State":
        """État décrit par le début de la partition (première mesure)."""
        state = cls()
        first = part.measures[0]
        clef, key, time = (_attribute(first, k) for k in ("clef", "key", "time"))
        state.clef = clef.value if clef else None
        state.fifths = key.value["fifths"] if key else 0
        if time is None:   # chiffrage écrit plus loin : c'est lui qui est au début
            time = next((_attribute(m, "time") for m in part.measures if _attribute(m, "time")),
                        None)
        state.time = (time.value["beats"], time.value["beat_type"]) if time else None
        return state


def _attribute(measure: Measure, kind: str) -> Symbol | None:
    return next((s for s in measure.attributes if s.kind == kind), None)


def _score_def(model: ScoreModel, parts: list[Part]) -> str:
    """Début de la partition : une portée par partie, avec ses clé, armure et chiffrage."""
    first_time = next((_attribute(m, "time") for m in parts[0].measures
                       if _attribute(m, "time")), None) if parts else None
    meter = ""
    if first_time is not None:
        meter = (f' meter.count="{first_time.value["beats"]}"'
                 f' meter.unit="{first_time.value["beat_type"]}"')
    staves = []
    for n, part in enumerate(parts, 1):
        first = part.measures[0]
        clef = _attribute(first, "clef")
        key = _attribute(first, "key")
        label = quoteattr(part.name or model.instrument or "")
        staves.append(f'<staffDef n="{n}" lines="5" label={label}{_clef_attrs(clef, "clef.")}'
                      f' key.sig="{_key_sig(key.value["fifths"] if key else 0)}"/>')
    return (f'<scoreDef{meter}><staffGrp{" symbol=\"brace\"" if len(parts) > 1 else ""}>'
            + "".join(staves) + "</staffGrp></scoreDef>")


def _clef_attrs(clef: Symbol | None, prefix: str) -> str:
    value = clef.value if clef is not None else {"sign": "G", "line": 2}
    shape = CLEF_SHAPES.get(value.get("sign"), "G")
    attrs = f' {prefix}shape="{shape}"'
    if shape != "perc":
        attrs += f' {prefix}line="{value.get("line") or 2}"'
    change = value.get("octave_change") or 0
    if change:
        attrs += f' {prefix}dis="8" {prefix}dis.place="{"below" if change < 0 else "above"}"'
    return attrs


def _key_sig(fifths: int) -> str:
    return "0" if fifths == 0 else f"{abs(fifths)}{'s' if fifths > 0 else 'f'}"


def _changes(measures: list[Measure], states: list[_State]) -> list[str]:
    """Changement d'armure ou de chiffrage au début de ces mesures (ce qui ne change rien
    à l'état en cours, comme le début de la partition, n'est pas réécrit)."""
    out = []
    for measure, state in zip(measures, states, strict=True):
        key, time = _attribute(measure, "key"), _attribute(measure, "time")
        attrs = ""
        if time is not None:
            value = (time.value["beats"], time.value["beat_type"])
            if state.time is not None and value != state.time:
                attrs += f' meter.count="{value[0]}" meter.unit="{value[1]}"'
            state.time = value
        if key is not None:
            if key.value["fifths"] != state.fifths:
                attrs += f' key.sig="{_key_sig(key.value["fifths"])}"'
            state.fifths = key.value["fifths"]
        if attrs and not out:
            out.append(f"<scoreDef{attrs}/>")
    return out


def _measure(measures: list[Measure], states: list[_State], ids: _Ids,
             controls: list[str]) -> str:
    first = measures[0]
    measure_id = ids.make("m", first.id, ids.measures)
    staves = []
    for n, (measure, state) in enumerate(zip(measures, states, strict=True), 1):
        staves.append(f'<staff n="{n}">{_layers(measure, state, ids)}</staff>')
    return (f'<measure xml:id="{measure_id}" n="{first.number}">' + "".join(staves)
            + "".join(controls) + "</measure>")


def _control_events(model: ScoreModel, parts: list[Part], ids: _Ids) -> dict[int, list[str]]:
    """Liaisons, soufflets, nuances, points d'orgue et tempo, rangés par mesure (rang)."""
    out: dict[int, list[str]] = defaultdict(list)
    for n, part in enumerate(parts, 1):
        for rank, measure in enumerate(part.measures):
            if n == 1:
                tempo = _attribute(measure, "tempo")
                value = tempo.value if tempo else (
                    {"text": model.tempo} if rank == 0 and model.tempo else None)
                if value:
                    out[rank].append(_tempo(value))
            for event in measure.events:
                name = ids.symbol(event.id)
                if event.value.get("dynamic"):
                    out[rank].append(f'<dynam staff="{n}" startid="#{name}">'
                                     f'{escape(event.value["dynamic"])}</dynam>')
                if "fermata" in (event.value.get("articulations") or []):
                    out[rank].append(f'<fermata staff="{n}" startid="#{name}"/>')
        for span in marks.spans(part):
            ends = f'startid="#{ids.symbol(span.start.id)}" endid="#{ids.symbol(span.end.id)}"'
            if span.kind == "slur":
                out[span.start_rank].append(f'<slur staff="{n}" {ends}/>')
            else:
                form = "cres" if span.form == "crescendo" else "dim"
                out[span.start_rank].append(f'<hairpin form="{form}" staff="{n}" {ends}/>')
    return out


def _tempo(value: dict) -> str:
    """Indication de tempo au début de la mesure : texte et métronome (« ♩ = 96 »)."""
    attrs = ' staff="1" tstamp="1" place="above"'
    per_minute, beat = value.get("per_minute"), value.get("beat")
    unit = marks.beat_unit(Fraction(beat)) if beat else None
    if per_minute and unit:
        mei_unit = {"whole": "1", "half": "2", "quarter": "4", "eighth": "8", "16th": "16"}
        attrs += f' mm="{per_minute}" mm.unit="{mei_unit[unit[0]]}"'
        if unit[1]:
            attrs += ' mm.dots="1"'
    text = escape(value.get("text") or "")
    if per_minute and unit:
        text = (text + " " if text else "") + f"\u2669 = {per_minute}"
    return f"<tempo{attrs}>{text}</tempo>"


def _layers(measure: Measure, state: _State, ids: _Ids) -> str:
    """Les voix d'une mesure (une couche MEI par voix)."""
    clef = _attribute(measure, "clef")
    clef_change = ""
    if clef is not None:
        if state.clef is not None and clef.value != state.clef:
            clef_change = f"<clef{_clef_attrs(clef, '')}/>"
        state.clef = clef.value
    multirest = _attribute(measure, "multirest")
    if multirest is not None:
        name = ids.symbol(multirest.id)
        count = multirest.value.get("count") or 1
        return f'<layer n="1">{clef_change}<multiRest xml:id="{name}" num="{count}"/></layer>'
    voices: dict[int, list[Symbol]] = {}
    for event in measure.events:
        voices.setdefault(event.value.get("voice") or 1, []).append(event)
    if not voices:
        return f'<layer n="1">{clef_change}<mSpace/></layer>'
    layers = []
    for rank, voice in enumerate(sorted(voices), 1):
        content = _events(voices[voice], state.fifths, ids)
        layers.append(f'<layer n="{rank}">{clef_change if rank == 1 else ""}{content}</layer>')
    return "".join(layers)


def _events(events: list[Symbol], fifths: int, ids: _Ids) -> str:
    """Notes, accords et silences d'une voix, avec les nolets regroupés."""
    groups: list[list[Symbol]] = []       # une note seule, ou un accord
    for event in events:
        if event.kind == "note" and event.value.get("chord") and groups \
                and groups[-1][0].kind == "note":
            groups[-1].append(event)
        else:
            groups.append([event])
    accidentals: dict[tuple[str, int], int] = {}   # altérations en cours dans la mesure
    out: list[str] = []
    tuplet: tuple | None = None
    tuplet_left = Fraction(0)
    for group in groups:
        head = group[0]
        ratio = tuple(head.value.get("tuplet") or ()) or None
        if tuplet is not None and (ratio != tuplet or tuplet_left <= 0):
            out.append("</tuplet>")
            tuplet = None
        if ratio and tuplet is None:
            actual, normal = ratio
            out.append(f'<tuplet num="{actual}" numbase="{normal}">')
            tuplet = ratio
            tuplet_left = _written(head) * normal
        out.append(_group(group, fifths, accidentals, ids))
        if tuplet is not None:
            tuplet_left -= _duration(head)
    if tuplet is not None:
        out.append("</tuplet>")
    return "".join(out)


def _duration(symbol: Symbol) -> Fraction:
    return symbol.duration or Fraction(0)


def _written(symbol: Symbol) -> Fraction:
    """Durée écrite (sans point ni nolet), en noires."""
    duration = _duration(symbol)
    dots = symbol.value.get("dots") or 0
    duration /= 2 - Fraction(1, 2 ** dots)
    ratio = symbol.value.get("tuplet")
    if ratio:
        duration = duration * ratio[0] / ratio[1]
    return duration


def _dur_attrs(symbol: Symbol) -> str:
    written = _written(symbol)
    dur = MEI_DURATIONS.get(written) or HEAD_DURATIONS.get(symbol.value.get("head"), "4")
    attrs = f' dur="{dur}"'
    dots = symbol.value.get("dots") or 0
    if dots:
        attrs += f' dots="{dots}"'
    return attrs


def _group(group: list[Symbol], fifths: int, accidentals: dict, ids: _Ids) -> str:
    head = group[0]
    if head.kind == "rest":
        name = ids.symbol(head.id)
        if head.value.get("full_measure"):
            return f'<mRest xml:id="{name}"/>'
        return f'<rest xml:id="{name}"{_dur_attrs(head)}/>'
    grace = ' grace="unacc"' if head.value.get("grace") else ""
    notes = [_note(note, fifths, accidentals, ids) for note in group]
    if len(group) == 1:
        return notes[0].replace("<note ", f"<note{_dur_attrs(head)}{grace} ", 1)
    return f"<chord{_dur_attrs(head)}{grace}>" + "".join(notes) + "</chord>"


def _note(note: Symbol, fifths: int, accidentals: dict, ids: _Ids) -> str:
    value = note.value
    name = ids.symbol(note.id)
    step, octave = value.get("step"), value.get("octave")
    if step is None or octave is None:     # percussion : hauteur sans nom de note
        step, octave = "B", 4
    alter = value.get("alter") or 0
    # Altération à dessiner : seulement si elle diffère de ce que donnent l'armure et les
    # altérations précédentes de la mesure.
    current = accidentals.get((step, octave), key_alter(fifths, step))
    if alter != current:
        accid = f' accid="{ACCIDENTALS.get(alter, "n")}"'
    else:
        accid = f' accid.ges="{ACCIDENTALS.get(alter, "n")}"' if alter else ""
    accidentals[(step, octave)] = alter
    tie = ""
    if value.get("tie_start") and value.get("tie_stop"):
        tie = ' tie="m"'
    elif value.get("tie_start"):
        tie = ' tie="i"'
    elif value.get("tie_stop"):
        tie = ' tie="t"'
    head = ' head.shape="x"' if value.get("head") == "x" else ""
    opening = f'<note xml:id="{name}" pname="{step.lower()}" oct="{octave}"{accid}{tie}{head}'
    artic = " ".join(marks.MEI_ARTICULATIONS[a] for a in value.get("articulations") or []
                     if a in marks.MEI_ARTICULATIONS)
    if artic:
        return f'{opening}><artic artic="{artic}"/></note>'
    return f"{opening}/>"
