"""Écriture des fichiers exportés : MuseScore (.mscz), MusicXML, MIDI.

L'instrument de la partie (choisi, ou reconnu d'après son nom) donne au MusicXML et au
MuseScore son son et sa transposition, et au MIDI sa hauteur réelle.
Sans MuseScore sur la machine, l'export MuseScore écrit un MusicXML à la place (même nom,
extension .musicxml) et le dit : MuseScore l'ouvrira très bien plus tard.
"""

import re
import sqlite3
from pathlib import Path

from recomuse.export.midi import model_to_midi
from recomuse.export.musescore import MuseScoreError, convert, find_musescore
from recomuse.export.musicxml import model_to_musicxml
from recomuse.export.notation import exported_parts
from recomuse.instruments.parts import instrument_of
from recomuse.instruments.table import InstrumentTable, load_table
from recomuse.model import conductor
from recomuse.model.score import ScoreModel
from recomuse.model.store import load_model

# Formats proposés et leur extension.
FORMATS = {"musescore": ".mscz", "musicxml": ".musicxml", "midi": ".mid"}


class ExportError(RuntimeError):
    """Export impossible ; `code` est traduit par l'interface."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _part_instruments(model: ScoreModel, table: InstrumentTable) -> list:
    """Instrument et version de chaque partie exportée d'un conducteur."""
    result = []
    for group in exported_parts(model):
        part = group[0]
        instrument = table.get(part.instrument_id)
        variant = instrument.variant(part.variant_id) if instrument else None
        if variant is None:
            clef = next((s for m in part.measures for s in m.attributes if s.kind == "clef"),
                        None)
            found = table.detect(part.name, clef.value.get("sign") if clef else None)
            instrument, variant = found if found else (None, None)
        result.append((instrument, variant))
    return result


def default_name(model: ScoreModel) -> str:
    """Nom de fichier proposé : « Titre - Instrument », sans caractères interdits."""
    instrument = model.instrument or (model.parts[0].name if model.parts else None)
    words = [w for w in (model.title, instrument) if w]
    name = " - ".join(words) or "Partition"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .") or "Partition"


def export_score(conn: sqlite3.Connection, score_id: int, fmt: str, path: Path | str) -> dict:
    """Écrit la partition dans le format demandé. Renvoie {"path": fichier écrit,
    "format": format écrit, "fallback": None ou la raison d'un format de secours}."""
    if fmt not in FORMATS:
        raise ExportError("unknown_format")
    model = load_model(conn, score_id)
    if model is None:
        raise ExportError("score_not_found")
    table = load_table()
    known = instrument_of(model, table)
    instrument = table.get(known["instrument_id"])
    variant = instrument.variant(known["variant_id"]) if instrument else None
    # Conducteur : chaque partie a son instrument (choisi, ou reconnu d'après son nom).
    instruments = (_part_instruments(model, table) if conductor.is_conductor(model)
                   else None)

    path = Path(path)
    if path.suffix.lower() != FORMATS[fmt]:
        path = path.with_name(path.name + FORMATS[fmt])
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "midi":
        path.write_bytes(model_to_midi(model, instrument, variant, instruments))
        return {"path": str(path), "format": fmt, "fallback": None}
    musicxml = model_to_musicxml(model, instrument, variant, instruments)
    if fmt == "musicxml":
        path.write_text(musicxml, encoding="utf-8")
        return {"path": str(path), "format": fmt, "fallback": None}

    executable = find_musescore()
    if executable is None:
        fallback = path.with_suffix(FORMATS["musicxml"])
        fallback.write_text(musicxml, encoding="utf-8")
        return {"path": str(fallback), "format": "musicxml", "fallback": "musescore_not_found"}
    try:
        convert(executable, musicxml, path)
    except MuseScoreError as error:
        fallback = path.with_suffix(FORMATS["musicxml"])
        fallback.write_text(musicxml, encoding="utf-8")
        return {"path": str(fallback), "format": "musicxml", "fallback": error.code}
    return {"path": str(path), "format": fmt, "fallback": None}
