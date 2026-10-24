"""Modèle interne → MusicXML 4.0 (« partwise »), le format d'échange des logiciels de
partitions (MuseScore, Finale, Sibelius, Dorico...).

Ce qui est écrit : titre, compositeurs, tempo écrit ; pour chaque partie son nom, son son
MIDI et sa transposition (une partie de trompette en si bémol sonne un ton plus bas que
écrit : MuseScore la jouera juste) ; clés, armures, chiffrages et leurs changements ;
notes (hauteur, durée, points, nolets, liaisons, accords, petites notes, voix), silences,
pauses multiples, lettres de répétition. Deux portées du même instrument (piano) forment
une seule partie à deux portées.

La partition est écrite telle qu'elle est dans le modèle : une mesure dont le compte est
faux reste fausse (le musicien la verra dans MuseScore).
"""

import math
from datetime import date
from fractions import Fraction
from xml.sax.saxutils import escape

from recomuse import __version__
from recomuse.export.notation import Accidentals, exported_parts, note_type, written
from recomuse.instruments.table import Instrument, Variant
from recomuse.model.score import Measure, Part, ScoreModel, Symbol

ALTER_NAMES = {-2: "flat-flat", -1: "flat", 0: "natural", 1: "sharp", 2: "double-sharp"}
# Voix MusicXML d'une portée : la portée 2 du piano a les voix 5 à 8.
VOICES_PER_STAFF = 4


def model_to_musicxml(model: ScoreModel, instrument: Instrument | None = None,
                      variant: Variant | None = None,
                      instruments: list[tuple[Instrument | None, Variant | None]] | None = None
                      ) -> str:
    """Texte MusicXML de la partition. `instrument`, `variant` : l'instrument de la partie
    (son MIDI et transposition) ; sans eux, la partie est écrite comme elle sonne.
    `instruments` : pour un conducteur, l'instrument de chaque partie (voir
    notation.exported_parts), à la place."""
    groups = exported_parts(model)
    if instruments is None:
        instruments = [(instrument, variant if n == 0 else None) for n in range(len(groups))]
    divisions = _divisions(model)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           ('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
           '"http://www.musicxml.org/dtds/partwise.dtd">'),
           '<score-partwise version="4.0">']
    if model.title:
        out.append(f"<work><work-title>{escape(model.title)}</work-title></work>")
    out.append("<identification>")
    out += [f'<creator type="composer">{escape(c)}</creator>' for c in model.composers]
    out.append(f"<encoding><software>RECOmuse {__version__}</software>"
               f"<encoding-date>{date.today().isoformat()}</encoding-date></encoding>")
    out.append("</identification>")

    out.append("<part-list>")
    for n, staves in enumerate(groups, 1):
        name = staves[0].name or model.instrument or ""
        percussion = _is_percussion(staves[0])
        this_instrument = instruments[n - 1][0] if n <= len(instruments) else None
        program = this_instrument.midi_program if this_instrument else 1
        channel = 10 if percussion else n % 16 or 1      # le canal 10 est celui des batteries
        out.append(f'<score-part id="P{n}"><part-name>{escape(name)}</part-name>'
                   f'<score-instrument id="P{n}-I1"><instrument-name>{escape(name)}'
                   f"</instrument-name></score-instrument>"
                   f'<midi-instrument id="P{n}-I1"><midi-channel>{channel}'
                   f"</midi-channel><midi-program>{program}</midi-program></midi-instrument>"
                   "</score-part>")
    out.append("</part-list>")

    for n, staves in enumerate(groups, 1):
        out.append(f'<part id="P{n}">')
        out += _part(model, staves, divisions,
                     instruments[n - 1][1] if n <= len(instruments) else None, with_tempo=n == 1)
        out.append("</part>")
    out.append("</score-partwise>")
    return "\n".join(out)


# --- Durées -------------------------------------------------------------------------------


def _divisions(model: ScoreModel) -> int:
    """Nombre de divisions de la noire : toutes les durées doivent en être des multiples
    (3 pour des triolets de croches, 4 pour des doubles croches...)."""
    denominators = {1}
    for symbol in model.symbols():
        if symbol.kind in ("note", "rest") and symbol.duration is not None:
            denominators.add(symbol.duration.denominator)
        elif symbol.kind == "time":
            denominators.add(Fraction(4 * symbol.value["beats"], symbol.value["beat_type"])
                             .denominator)
    return math.lcm(*denominators)


def _ticks(duration: Fraction | None, divisions: int) -> int:
    return max(1, round((duration if duration is not None else Fraction(1)) * divisions))


# --- Une partie ---------------------------------------------------------------------------


def _part(model: ScoreModel, staves: list[Part], divisions: int,
          variant: Variant | None, with_tempo: bool = True) -> list[str]:
    """Mesures d'une partie. `with_tempo` : la première partie porte le tempo (une seule
    fois dans un conducteur)."""
    out: list[str] = []
    number = 1
    fifths = [0] * len(staves)
    current_time: Fraction | None = None
    for index in range(len(staves[0].measures)):
        measures = [staff.measures[index] for staff in staves]
        first = measures[0]
        time = _attribute(first, "time")
        if time is not None:
            current_time = Fraction(4 * time.value["beats"], time.value["beat_type"])
        length = current_time or _played_length(measures)
        multirest = _attribute(first, "multirest")
        count = (multirest.value.get("count") or 1) if multirest is not None else 1

        out.append(f'<measure number="{number}">')
        out += _attributes(measures, index == 0, divisions, fifths, variant, len(staves), count)
        if index == 0 and with_tempo and model.tempo:
            out.append('<direction placement="above"><direction-type>'
                       f"<words>{escape(model.tempo)}</words></direction-type></direction>")
        for mark in first.marks:
            out.append('<direction placement="above"><direction-type>'
                       f"<rehearsal>{escape(mark)}</rehearsal></direction-type></direction>")
        for rank, measure in enumerate(measures):
            if rank:
                out.append(f"<backup><duration>{_ticks(length, divisions)}</duration></backup>")
            if multirest is not None or not measure.events:
                out.append(_measure_rest(length, divisions, rank + 1))
            else:
                out += _events(measure, divisions, fifths[rank], rank + 1)
        out.append("</measure>")
        # Les autres mesures d'une pause multiple : des mesures de silence.
        for k in range(1, count):
            out.append(f'<measure number="{number + k}">')
            for rank in range(len(staves)):
                if rank:
                    out.append(f"<backup><duration>{_ticks(length, divisions)}"
                               "</duration></backup>")
                out.append(_measure_rest(length, divisions, rank + 1))
            out.append("</measure>")
        number += count
    return out


def _attribute(measure: Measure, kind: str) -> Symbol | None:
    return next((s for s in measure.attributes if s.kind == kind), None)


def _is_percussion(part: Part) -> bool:
    return any(s.kind == "clef" and s.value.get("sign") == "percussion"
               for m in part.measures for s in m.attributes)


def _played_length(measures: list[Measure]) -> Fraction:
    """Durée d'une mesure sans chiffrage connu : la plus longue de ses voix."""
    longest = Fraction(0)
    for measure in measures:
        voices: dict[int, Fraction] = {}
        for event in measure.events:
            if event.value.get("chord") or event.value.get("grace"):
                continue
            voice = event.value.get("voice") or 1
            voices[voice] = voices.get(voice, Fraction(0)) + (event.duration or Fraction(0))
        longest = max([longest, *voices.values()])
    return longest or Fraction(4)


def _attributes(measures: list[Measure], first: bool, divisions: int, fifths: list[int],
                variant: Variant | None, staves: int, count: int) -> list[str]:
    """Divisions, armure, chiffrage, portées, clés, transposition, pause multiple."""
    parts: list[str] = []
    if first:
        parts.append(f"<divisions>{divisions}</divisions>")
    key = _attribute(measures[0], "key")
    if key is not None:
        for rank in range(staves):
            fifths[rank] = key.value["fifths"]
        parts.append(f"<key><fifths>{key.value['fifths']}</fifths></key>")
    elif first:
        parts.append("<key><fifths>0</fifths></key>")
    time = _attribute(measures[0], "time")
    if time is not None:
        parts.append(f"<time><beats>{time.value['beats']}</beats>"
                     f"<beat-type>{time.value['beat_type']}</beat-type></time>")
    if first and staves > 1:
        parts.append(f"<staves>{staves}</staves>")
    for rank, measure in enumerate(measures, 1):
        clef = _attribute(measure, "clef")
        if clef is not None:
            parts.append(_clef(clef.value, rank if staves > 1 else None))
        elif first:
            parts.append(_clef({"sign": "G", "line": 2}, rank if staves > 1 else None))
    transposes = (variant is not None and variant.transpose is not None
                  and (variant.transpose.steps or variant.transpose.semitones))
    if first and transposes:
        parts.append(_transpose(variant))
    if count > 1:
        parts.append(f"<measure-style><multiple-rest>{count}</multiple-rest></measure-style>")
    return [f"<attributes>{''.join(parts)}</attributes>"] if parts else []


def _clef(value: dict, staff: int | None) -> str:
    number = f' number="{staff}"' if staff else ""
    if value.get("sign") == "percussion":
        return f"<clef{number}><sign>percussion</sign></clef>"
    change = value.get("octave_change") or 0
    octave = f"<clef-octave-change>{change}</clef-octave-change>" if change else ""
    return (f"<clef{number}><sign>{value.get('sign', 'G')}</sign>"
            f"<line>{value.get('line') or 2}</line>{octave}</clef>")


def _transpose(variant: Variant) -> str:
    """Transposition de l'instrument (de la note écrite à la note entendue), découpée
    comme le veut MusicXML : intervalle dans l'octave, plus des octaves."""
    interval = variant.transpose
    octaves = int(interval.semitones / 12)
    diatonic = interval.steps - 7 * octaves
    chromatic = interval.semitones - 12 * octaves
    change = f"<octave-change>{octaves}</octave-change>" if octaves else ""
    return (f"<transpose><diatonic>{diatonic}</diatonic>"
            f"<chromatic>{chromatic}</chromatic>{change}</transpose>")


def _measure_rest(length: Fraction, divisions: int, staff: int) -> str:
    return (f'<note><rest measure="yes"/><duration>{_ticks(length, divisions)}</duration>'
            f"<voice>{(staff - 1) * VOICES_PER_STAFF + 1}</voice><staff>{staff}</staff></note>")


# --- Notes et silences --------------------------------------------------------------------


def _events(measure: Measure, divisions: int, fifths: int, staff: int) -> list[str]:
    """Toutes les voix d'une portée, l'une après l'autre (retour au début de la mesure
    entre deux voix)."""
    voices: dict[int, list[Symbol]] = {}
    for event in measure.events:
        voices.setdefault(event.value.get("voice") or 1, []).append(event)
    out: list[str] = []
    accidentals = Accidentals(fifths)
    for rank, voice in enumerate(sorted(voices)):
        events = voices[voice]
        if rank:
            previous = voices[sorted(voices)[rank - 1]]
            elapsed = sum((e.duration or Fraction(0)) for e in previous
                          if not e.value.get("chord") and not e.value.get("grace"))
            if elapsed:
                out.append(f"<backup><duration>{_ticks(elapsed, divisions)}</duration></backup>")
        number = (staff - 1) * VOICES_PER_STAFF + rank + 1
        tuplets = _tuplet_marks(events)
        for event in events:
            out.append(_note(event, divisions, number, staff, accidentals, tuplets.get(event.id)))
    return out


def _tuplet_marks(events: list[Symbol]) -> dict[str, str]:
    """Début et fin de chaque groupe de nolet (« start », « stop ») : un groupe se ferme
    quand sa durée est remplie (3 croches de triolet = une noire)."""
    marks: dict[str, str] = {}
    left = Fraction(0)
    last: Symbol | None = None
    ratio = None
    for event in events:
        if event.value.get("chord") or event.value.get("grace"):
            continue
        current = tuple(event.value.get("tuplet") or ()) or None
        if ratio is not None and (current != ratio or left <= 0):
            if last is not None:
                marks[last.id] = "stop"
            ratio = None
        if current and ratio is None:
            ratio = current
            left = written(event) * current[1]
            marks[event.id] = "start"
        if ratio is not None:
            left -= event.duration or Fraction(0)
            last = event
    if ratio is not None and last is not None:
        marks[last.id] = "stop" if marks.get(last.id) != "start" else "start"
    return marks


def _note(event: Symbol, divisions: int, voice: int, staff: int, accidentals: Accidentals,
          tuplet: str | None) -> str:
    value = event.value
    parts: list[str] = []
    grace = bool(value.get("grace"))
    if grace:
        parts.append('<grace slash="yes"/>')
    if value.get("chord"):
        parts.append("<chord/>")
    if event.kind == "rest":
        parts.append('<rest measure="yes"/>' if value.get("full_measure") else "<rest/>")
    elif value.get("step") is None:
        parts.append("<unpitched><display-step>C</display-step>"
                     "<display-octave>5</display-octave></unpitched>")
    else:
        alter = value.get("alter") or 0
        alter_tag = f"<alter>{alter}</alter>" if alter else ""
        parts.append(f"<pitch><step>{value['step']}</step>{alter_tag}"
                     f"<octave>{value['octave']}</octave></pitch>")
    if not grace:
        parts.append(f"<duration>{_ticks(event.duration, divisions)}</duration>")
    if value.get("tie_stop"):
        parts.append('<tie type="stop"/>')
    if value.get("tie_start"):
        parts.append('<tie type="start"/>')
    parts.append(f"<voice>{voice}</voice>")
    kind = note_type(event)
    if kind and not (event.kind == "rest" and value.get("full_measure")):
        parts.append(f"<type>{kind}</type>")
    parts += ["<dot/>"] * (value.get("dots") or 0)
    if event.kind == "note" and value.get("step") is not None:
        printed = accidentals.printed(value["step"], value["octave"], value.get("alter") or 0)
        if printed is not None:
            parts.append(f"<accidental>{ALTER_NAMES.get(printed, 'natural')}</accidental>")
    ratio = value.get("tuplet")
    if ratio:
        parts.append(f"<time-modification><actual-notes>{ratio[0]}</actual-notes>"
                     f"<normal-notes>{ratio[1]}</normal-notes></time-modification>")
    if value.get("head") == "x":
        parts.append("<notehead>x</notehead>")
    parts.append(f"<staff>{staff}</staff>")
    notations = []
    if value.get("tie_stop"):
        notations.append('<tied type="stop"/>')
    if value.get("tie_start"):
        notations.append('<tied type="start"/>')
    if tuplet:
        notations.append(f'<tuplet type="{tuplet}"/>')
    if notations:
        parts.append(f"<notations>{''.join(notations)}</notations>")
    return f"<note>{''.join(parts)}</note>"
