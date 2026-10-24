"""Instrument d'une partition, et transposition d'une partition enregistrée.

- instrument_of : l'instrument et la version d'une partie (choisis par l'utilisateur, ou
  reconnus d'après le nom de la partie et sa clé) ;
- set_instrument : l'utilisateur corrige l'instrument reconnu ;
- check / transpose_score : ce que donnerait une transposition (armures, notes hors de
  l'étendue, octave conseillée), puis la nouvelle partition transposée, enregistrée à
  côté de celle d'origine (qui ne change pas).

Les demandes viennent de l'interface :
    {"mode": "instrument", "target": {"instrument": "euphonium", "variant": "bb_treble"},
     "source": {...} (facultatif : l'instrument de la partie), "octave": 0, "name": "..."}
    {"mode": "interval", "interval": "M2", "direction": "up" | "down", "octave": 0,
     "name": "..."}
« name » est le nom de la nouvelle partie, écrit par l'interface dans la langue choisie.
"""

import sqlite3

from recomuse.instruments.table import InstrumentTable, Interval, load_table
from recomuse.instruments.transpose import Request, for_instruments, transpose_model
from recomuse.library import summary
from recomuse.model.score import ScoreModel
from recomuse.model.store import load_model, save_model


class TranspositionError(ValueError):
    """Demande impossible (instrument inconnu, percussions, intervalle illisible...)."""


def table_for_interface(table: InstrumentTable | None = None) -> list[dict]:
    """La table des instruments, telle que l'interface la propose."""
    table = table or load_table()
    return [{"id": i.id, "label": i.label,
             "variants": [{"id": v.id, "key": v.key, "clef": v.clef,
                           "transposable": v.transpose is not None} for v in i.variants]}
            for i in table.instruments if i.variants]


def instrument_of(model: ScoreModel, table: InstrumentTable | None = None) -> dict:
    """Instrument et version de la partie : {"instrument_id", "variant_id", "detected"}
    (detected : reconnu d'après le nom, pas choisi par l'utilisateur)."""
    table = table or load_table()
    instrument = table.get(model.instrument_id)
    if instrument is not None and instrument.variant(model.variant_id) is not None:
        return {"instrument_id": instrument.id, "variant_id": model.variant_id,
                "detected": False}
    first_part = model.parts[0] if model.parts else None
    name = (first_part.name if first_part else None) or model.instrument
    clef = next((s for m in (first_part.measures if first_part else []) for s in m.attributes
                 if s.kind == "clef"), None)
    found = table.detect(name, clef.value.get("sign") if clef else None)
    if found is None:
        return {"instrument_id": None, "variant_id": None, "detected": True}
    return {"instrument_id": found[0].id, "variant_id": found[1].id, "detected": True}


def set_instrument(conn: sqlite3.Connection, score_id: int, instrument_id: str,
                   variant_id: str) -> dict:
    """Retient l'instrument de la partie choisi par l'utilisateur."""
    table = load_table()
    instrument = table.get(instrument_id)
    if instrument is None or instrument.variant(variant_id) is None:
        raise TranspositionError(f"Instrument inconnu : {instrument_id} / {variant_id}")
    model = _load(conn, score_id)
    model.instrument_id, model.variant_id = instrument_id, variant_id
    save_model(conn, score_id, model)
    return instrument_of(model, table)


def check(conn: sqlite3.Connection, score_id: int, request: dict) -> dict:
    """Ce que donnerait la transposition demandée, sans rien enregistrer."""
    model = _load(conn, score_id)
    return transpose_model(model, parse_request(model, request))[1]


def transpose_score(conn: sqlite3.Connection, score_id: int, request: dict) -> dict:
    """Enregistre la partition transposée comme une nouvelle partition. Renvoie
    {"score": son résumé, "report": compte rendu}."""
    model = _load(conn, score_id)
    result, report = transpose_model(model, parse_request(model, request))
    result.transposed_from = score_id
    result.instrument = request.get("name") or result.instrument
    row = conn.execute("SELECT source_path, source_kind, page_count FROM scores WHERE id = ?",
                       (score_id,)).fetchone()
    with conn:
        cursor = conn.execute(
            "INSERT INTO scores (title, part_name, source_path, source_kind, page_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (result.title, result.instrument, row[0], row[1], row[2]))
    new_id = cursor.lastrowid
    save_model(conn, new_id, result)
    return {"score": summary(new_id, result), "report": report}


def parse_request(model: ScoreModel, request: dict) -> Request:
    """Demande de l'interface → transposition à faire."""
    table = load_table()
    octave = int(request.get("octave") or 0)
    if not -3 <= octave <= 3:
        raise TranspositionError(f"Octave impossible : {octave}")
    if request.get("mode") == "interval":
        try:
            interval = Interval.parse(str(request.get("interval")))
        except ValueError as error:
            raise TranspositionError(str(error)) from None
        if request.get("direction") == "down":
            interval = -interval
        return Request(interval, octave)
    if request.get("mode") != "instrument":
        raise TranspositionError(f"Mode inconnu : {request.get('mode')}")
    source_ids = request.get("source") or {}
    if not source_ids:
        known = instrument_of(model, table)
        source_ids = {"instrument": known["instrument_id"], "variant": known["variant_id"]}
    source = _variant(table, source_ids)[1]
    target_instrument, target = _variant(table, request.get("target") or {})
    try:
        return for_instruments(source, target_instrument, target, octave)
    except ValueError as error:
        raise TranspositionError(str(error)) from None


def _variant(table: InstrumentTable, ids: dict):
    instrument = table.get(ids.get("instrument"))
    variant = instrument.variant(ids.get("variant")) if instrument else None
    if variant is None:
        raise TranspositionError(f"Instrument inconnu : {ids}")
    return instrument, variant


def _load(conn: sqlite3.Connection, score_id: int) -> ScoreModel:
    model = load_model(conn, score_id)
    if model is None:
        raise TranspositionError(f"Partition n° {score_id} introuvable.")
    return model
