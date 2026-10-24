"""Modèle interne → fichier MIDI (Standard MIDI File, type 1), à la hauteur RÉELLE.

Une partie de trompette en si bémol est écrite un ton plus haut qu'elle ne sonne : le
MIDI la joue comme on l'entend (do écrit → si bémol joué). Le son de chaque partie est
celui de son instrument (table des instruments, numéros General MIDI) ; les percussions
jouent sur le canal 10.

Une piste par portée, plus une piste de mesure (tempo, chiffrages). Le tempo vient de
l'indication écrite si elle donne un nombre (« ♩ = 120 »), sinon 100 à la noire.
Les petites notes ne sont pas jouées ; les notes liées n'en font qu'une.
"""

import re
import struct
from fractions import Fraction

from recomuse.export.notation import exported_parts
from recomuse.instruments.table import Instrument, Variant, midi_number
from recomuse.model.score import Measure, ScoreModel

TICKS_PER_QUARTER = 480
DEFAULT_TEMPO = 100                # noires par minute
VELOCITY = 80
DRUM_CHANNEL = 9                   # le « canal 10 » des musiciens (numéroté à partir de 0)
SNARE, HI_HAT = 38, 42             # sons de batterie (têtes normales, têtes en croix)


def model_to_midi(model: ScoreModel, instrument: Instrument | None = None,
                  variant: Variant | None = None) -> bytes:
    """Fichier MIDI de la partition (octets prêts à écrire)."""
    shift = variant.transpose.semitones if variant and variant.transpose else 0
    program = (instrument.midi_program if instrument else 1) - 1
    staves = [part for group in exported_parts(model) for part in group]
    timeline = _timeline(staves[0].measures) if staves else []
    tracks = [_conductor(model, staves[0].measures if staves else [], timeline)]
    channel = 0
    for staff in staves:
        percussion = any(s.kind == "clef" and s.value.get("sign") == "percussion"
                         for m in staff.measures for s in m.attributes)
        if percussion:
            this_channel = DRUM_CHANNEL
        else:
            this_channel = channel
            channel = channel + 1 if channel + 1 != DRUM_CHANNEL else channel + 2
            channel %= 16
        notes = _notes(staff.measures, timeline, shift, percussion)
        tracks.append(_track(staff.name or model.instrument or "", this_channel, program,
                             notes, percussion))
    header = struct.pack(">4sIHHH", b"MThd", 6, 1, len(tracks), TICKS_PER_QUARTER)
    return header + b"".join(tracks)


# --- Temps --------------------------------------------------------------------------------


def _timeline(measures: list[Measure]) -> list[tuple[Fraction, Fraction]]:
    """Début et durée (en noires) de chaque mesure. Une pause multiple dure autant de
    mesures que son nombre ; une mesure sans chiffrage connu dure sa voix la plus longue."""
    result = []
    start = Fraction(0)
    current: Fraction | None = None
    for measure in measures:
        time = next((s for s in measure.attributes if s.kind == "time"), None)
        if time is not None:
            current = Fraction(4 * time.value["beats"], time.value["beat_type"])
        length = current if current is not None else _longest_voice(measure)
        result.append((start, length * measure.length))
        start += length * measure.length
    return result


def _longest_voice(measure: Measure) -> Fraction:
    voices: dict[int, Fraction] = {}
    for event in measure.events:
        if event.value.get("chord") or event.value.get("grace"):
            continue
        voice = event.value.get("voice") or 1
        voices[voice] = voices.get(voice, Fraction(0)) + (event.duration or Fraction(0))
    return max(voices.values(), default=Fraction(4)) or Fraction(4)


def _ticks(quarters: Fraction) -> int:
    return round(quarters * TICKS_PER_QUARTER)


def tempo_of(text: str | None) -> int:
    """Tempo (noires par minute) d'une indication écrite : « ♩ = 120 » → 120."""
    match = re.search(r"(\d{2,3})", text or "")
    value = int(match.group(1)) if match else DEFAULT_TEMPO
    return value if 30 <= value <= 300 else DEFAULT_TEMPO


# --- Notes --------------------------------------------------------------------------------


def _notes(measures: list[Measure], timeline, shift: int,
           percussion: bool) -> list[tuple[int, int, int]]:
    """Notes jouées : (début, fin, hauteur MIDI), en tics."""
    notes: list[list[int]] = []
    open_ties: dict[int, list[int]] = {}      # hauteur → note liée vers la suivante
    for measure, (start, _) in zip(measures, timeline, strict=False):
        voices: dict[int, list] = {}
        for event in measure.events:
            voices.setdefault(event.value.get("voice") or 1, []).append(event)
        for events in voices.values():
            position = start
            chord_start = start
            for event in events:
                value = event.value
                if value.get("grace"):
                    continue
                duration = event.duration or Fraction(0)
                if value.get("chord"):
                    begin = chord_start
                else:
                    begin = chord_start = position
                    position += duration
                if event.kind != "note":
                    continue
                if percussion or value.get("step") is None:
                    pitch = HI_HAT if value.get("head") == "x" else SNARE
                else:
                    pitch = midi_number(value["step"], value.get("alter") or 0,
                                        value["octave"]) + shift
                if not 0 <= pitch <= 127:
                    continue
                first, last = _ticks(begin), _ticks(begin + duration)
                tied = open_ties.pop(pitch, None)
                if value.get("tie_stop") and tied is not None and tied[1] == first:
                    tied[1] = last                       # la note liée continue
                    note = tied
                else:
                    note = [first, last, pitch]
                    notes.append(note)
                if value.get("tie_start"):
                    open_ties[pitch] = note
    return [(a, b, p) for a, b, p in notes if b > a]


# --- Écriture du fichier ------------------------------------------------------------------


def _vlq(value: int) -> bytes:
    """Nombre en longueur variable (7 bits par octet), comme le veut le format MIDI."""
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(out))


def _chunk(events: list[tuple[int, int, bytes]]) -> bytes:
    """Piste MIDI : événements (tic, ordre, octets) triés, en temps relatifs."""
    body = b""
    now = 0
    for tick, _, data in sorted(events, key=lambda e: (e[0], e[1])):
        body += _vlq(tick - now) + data
        now = tick
    body += _vlq(0) + b"\xff\x2f\x00"           # fin de piste
    return struct.pack(">4sI", b"MTrk", len(body)) + body


def _text(kind: int, text: str) -> bytes:
    data = text.encode("utf-8")
    return bytes([0xFF, kind]) + _vlq(len(data)) + data


def _conductor(model: ScoreModel, measures: list[Measure], timeline) -> bytes:
    """Piste de mesure : titre, tempo, chiffrages."""
    tempo = 60_000_000 // tempo_of(model.tempo)
    events = [(0, 0, _text(0x03, model.title or "")),
              (0, 1, b"\xff\x51\x03" + tempo.to_bytes(3, "big"))]
    for measure, (start, _) in zip(measures, timeline, strict=False):
        time = next((s for s in measure.attributes if s.kind == "time"), None)
        if time is not None:
            beat_type = time.value["beat_type"]
            power = max(0, beat_type.bit_length() - 1)
            events.append((_ticks(start), 2, b"\xff\x58\x04" + bytes(
                [time.value["beats"], power, 24, 8])))
    return _chunk(events)


def _track(name: str, channel: int, program: int, notes, percussion: bool) -> bytes:
    events = [(0, 0, _text(0x03, name))]
    if not percussion:
        events.append((0, 1, bytes([0xC0 | channel, program & 0x7F])))
    for start, end, pitch in notes:
        events.append((start, 3, bytes([0x90 | channel, pitch, VELOCITY])))
        events.append((end, 2, bytes([0x80 | channel, pitch, 0])))   # arrêt avant reprise
    return _chunk(events)
