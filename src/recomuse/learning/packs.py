"""Packs d'apprentissage : partager ce que RECOmuse a appris avec les autres membres.

Un pack est un fichier « .recomuse-pack » (une archive ZIP de textes JSON) qui contient :
- manifest.json : identifiant du pack, auteur (facultatif), date, version de RECOmuse ;
- answers.json : les réponses de l'utilisateur aux questions (type de doute et réponse),
  qui nourrissent les règles apprises de celui qui importe le pack ;
- scores.json : pour chaque partie corrigée, l'empreinte de ses pages, ses corrections et
  ses réponses : un membre qui ouvre la même partie (même PDF, même scan) reprend ce
  travail au lieu de le refaire.

Le pack ne contient AUCUNE image ni partition (ni pages, ni extraits) : seulement des
valeurs de notes et de symboles, et les titres pour s'y retrouver. Les partitions sont
protégées par le droit d'auteur.

À l'import, tout est rangé à part (tables pack_*) : le journal des corrections reste
celui de l'utilisateur, et un pack peut être retiré d'un coup. Un même pack n'est
importé qu'une fois.
"""

import json
import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from recomuse import __version__
from recomuse.learning.memory import same_pages, score_work

EXTENSION = ".recomuse-pack"
# Version du format des packs : un pack plus récent que ce que ce RECOmuse connaît est
# refusé (il faut mettre RECOmuse à jour).
PACK_FORMAT = 1
# Taille maximale lue dans une archive (garde-fou contre un fichier qui n'est pas un pack).
MAX_ENTRY_BYTES = 50_000_000


class PackError(RuntimeError):
    """Pack impossible à lire ou à importer ; `code` est traduit par l'interface."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# --- Export -------------------------------------------------------------------------------


def export_pack(conn: sqlite3.Connection, path: Path | str, author: str | None = None,
                include_scores: bool = True) -> dict:
    """Écrit un pack avec tout ce que l'utilisateur a appris à RECOmuse. Renvoie
    {"path", "answers", "scores"} (nombres de réponses et de parties mises dedans)."""
    path = Path(path)
    if path.suffix != EXTENSION:
        path = path.with_name(path.name + EXTENSION)
    answers = [
        {"score_key": str(score_id), "signature": json.loads(signature), "choice_id": choice,
         "choice_label": label}
        for score_id, signature, choice, label in conn.execute(
            "SELECT score_id, signature, choice_id, choice_label FROM question_answers"
            " WHERE undone = 0 AND answered_by = 'user' AND signature IS NOT NULL ORDER BY id")]
    scores = _scores(conn) if include_scores else []
    manifest = {"format": PACK_FORMAT, "uuid": uuid.uuid4().hex,
                "author": (author or "").strip() or None,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "recomuse_version": __version__,
                "answers": len(answers), "scores": len(scores)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in (("manifest.json", manifest), ("answers.json", answers),
                           ("scores.json", scores)):
            archive.writestr(name, json.dumps(data, ensure_ascii=False, indent=1))
    return {"path": str(path), "answers": len(answers), "scores": len(scores)}


def _scores(conn: sqlite3.Connection) -> list[dict]:
    """Parties corrigées de l'utilisateur, avec l'empreinte de leurs pages."""
    prints: dict[int, list[tuple[int, str]]] = {}
    for score_id, number, value in conn.execute(
            "SELECT score_id, page_number, fingerprint FROM page_fingerprints"):
        prints.setdefault(score_id, []).append((number, value))
    result = []
    for score_id in sorted(prints):
        corrections, answers = score_work(conn, score_id)
        if not corrections and not answers:
            continue
        title, part_name = conn.execute("SELECT title, part_name FROM scores WHERE id = ?",
                                        (score_id,)).fetchone()
        result.append({"score_key": str(score_id), "title": title, "part_name": part_name,
                       "fingerprints": [value for _, value in sorted(prints[score_id])],
                       "corrections": corrections, "answers": answers})
    return result


# --- Import -------------------------------------------------------------------------------


def read_pack(path: Path | str) -> tuple[dict, list[dict], list[dict]]:
    """Lit un pack : (manifeste, réponses, parties). Lève PackError s'il est illisible."""
    try:
        with zipfile.ZipFile(path) as archive:
            data = {}
            for name in ("manifest.json", "answers.json", "scores.json"):
                info = archive.getinfo(name)
                if info.file_size > MAX_ENTRY_BYTES:
                    raise PackError("not_a_pack")
                data[name] = json.loads(archive.read(info).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise PackError("not_a_pack") from None
    manifest = data["manifest.json"]
    if not isinstance(manifest, dict) or "uuid" not in manifest:
        raise PackError("not_a_pack")
    if int(manifest.get("format", 0)) > PACK_FORMAT:
        raise PackError("pack_too_new")
    return manifest, data["answers.json"], data["scores.json"]


def import_pack(conn: sqlite3.Connection, path: Path | str) -> dict:
    """Importe un pack. Renvoie son résumé (voir list_packs)."""
    manifest, answers, scores = read_pack(path)
    if conn.execute("SELECT 1 FROM packs WHERE uuid = ?", (manifest["uuid"],)).fetchone():
        raise PackError("pack_already_imported")
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO packs (uuid, author, created_at, recomuse_version)"
                " VALUES (?, ?, ?, ?)",
                (manifest["uuid"], manifest.get("author"), manifest.get("created_at") or "",
                 manifest.get("recomuse_version")))
            pack_id = cursor.lastrowid
            conn.executemany(
                "INSERT INTO pack_answers (pack_id, score_key, signature, choice_id,"
                " choice_label) VALUES (?, ?, ?, ?, ?)",
                [(pack_id, str(a["score_key"]),
                  json.dumps(a["signature"], ensure_ascii=False, sort_keys=True),
                  a["choice_id"], a.get("choice_label")) for a in answers])
            conn.executemany(
                "INSERT INTO pack_scores (pack_id, score_key, title, part_name, fingerprints,"
                " corrections, answers) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(pack_id, str(s["score_key"]), s.get("title"), s.get("part_name"),
                  json.dumps(s["fingerprints"]), json.dumps(s["corrections"]),
                  json.dumps(s["answers"])) for s in scores])
    except (KeyError, TypeError, sqlite3.IntegrityError):
        raise PackError("not_a_pack") from None
    return next(p for p in list_packs(conn) if p["id"] == pack_id)


def list_packs(conn: sqlite3.Connection) -> list[dict]:
    """Packs importés, du plus récent au plus ancien, avec ce qu'ils apportent."""
    rows = conn.execute(
        "SELECT p.id, p.author, p.created_at, p.imported_at,"
        " (SELECT COUNT(*) FROM pack_answers a WHERE a.pack_id = p.id),"
        " (SELECT COUNT(*) FROM pack_scores s WHERE s.pack_id = p.id)"
        " FROM packs p ORDER BY p.id DESC")
    return [{"id": pack_id, "author": author, "created_at": created, "imported_at": imported,
             "answers": answers, "scores": scores}
            for pack_id, author, created, imported, answers, scores in rows]


def remove_pack(conn: sqlite3.Connection, pack_id: int) -> None:
    """Retire un pack et tout ce qu'il a apporté (ce qui a déjà été corrigé avec son aide
    reste corrigé : ces corrections sont dans le journal de l'utilisateur)."""
    with conn:
        conn.execute("DELETE FROM packs WHERE id = ?", (pack_id,))


# --- Utilisation par la mémoire des partitions ---------------------------------------------


def find_score(conn: sqlite3.Connection, prints: dict[int, str]) -> dict | None:
    """Une partie d'un pack qui a les mêmes pages : {"pack_id", "author", "created_at",
    "corrections", "answers"}, ou None. Le pack le plus récent l'emporte."""
    if not prints:
        return None
    wanted = [prints[n] for n in sorted(prints)]
    rows = conn.execute(
        "SELECT s.pack_id, p.author, p.created_at, s.fingerprints, s.corrections, s.answers"
        " FROM pack_scores s JOIN packs p ON p.id = s.pack_id ORDER BY s.pack_id DESC")
    for pack_id, author, created, fingerprints, corrections, answers in rows:
        if same_pages(json.loads(fingerprints), wanted):
            return {"pack_id": pack_id, "author": author, "created_at": created,
                    "corrections": json.loads(corrections), "answers": json.loads(answers)}
    return None
