"""
history.py
----------
Historial y caché de análisis. Guarda cada extracción en una base SQLite para
poder recuperarla al instante en vez de reprocesar el mismo audio (que cuesta
decenas de segundos de CPU).

Un archivo se identifica por el SHA-256 de su contenido, no por su ruta: así el
historial sigue valiendo aunque muevas o renombres el MP3, y reconoce como
iguales dos copias con distinto nombre.

La clave de caché incluye además las opciones que cambian el resultado (método,
tonalidad, tempo, separación). El dispositivo de Demucs no entra: no altera la
salida.

Uso:
    h = History(directorio)
    fp = History.fingerprint("cancion.mp3")
    hit = h.find(fp, opciones)          # ExtractionResult o None
    h.save(resultado, "cancion.mp3", fp, opciones)
    h.recent()                          # lista de HistoryEntry, más reciente primero
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from chord_extractor import ChordSegment, ExtractionResult

DB_NAME = "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint    TEXT    NOT NULL,
    options_key    TEXT    NOT NULL,
    source_path    TEXT    NOT NULL,
    filename       TEXT    NOT NULL,
    file_size      INTEGER,
    method         TEXT    NOT NULL,
    separated      INTEGER NOT NULL,
    key            TEXT,
    tempo_bpm      REAL,
    audio_duration REAL,
    chords_json    TEXT    NOT NULL,
    created_at     TEXT    NOT NULL,
    UNIQUE (fingerprint, options_key)
);
CREATE INDEX IF NOT EXISTS idx_created ON analyses (created_at DESC);
"""


@dataclass
class HistoryEntry:
    id: int
    filename: str
    source_path: str
    method: str
    separated: bool
    key: Optional[str]
    tempo_bpm: Optional[float]
    chord_count: int
    audio_duration: float
    created_at: datetime

    @property
    def file_exists(self) -> bool:
        return bool(self.source_path) and os.path.isfile(self.source_path)


def options_key(method: str, with_key: bool, with_tempo: bool,
                separate: bool) -> str:
    """Identifica la combinación de opciones que afecta al resultado."""
    return f"{method}|k{int(with_key)}|t{int(with_tempo)}|s{int(separate)}"


class HistoryUnavailable(Exception):
    """La base no se pudo abrir (disco lleno, permisos, archivo corrupto)."""


class History:
    def __init__(self, directory: str):
        self.path = os.path.join(directory, DB_NAME)
        try:
            with self._connect() as con:
                con.executescript(_SCHEMA)
        except sqlite3.Error as exc:
            raise HistoryUnavailable(str(exc)) from exc

    def _connect(self) -> sqlite3.Connection:
        # Una conexión corta por operación: así el hilo del análisis y el de la
        # interfaz nunca comparten una, que sqlite no permite por defecto.
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------------------------------------- huella
    @staticmethod
    def fingerprint(path: str, chunk: int = 1 << 20) -> str:
        """SHA-256 del contenido del archivo, leído por bloques."""
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(chunk), b""):
                digest.update(block)
        return digest.hexdigest()

    # ------------------------------------------------------------- lectura
    def find(self, fingerprint: str, opts_key: str
             ) -> Optional[tuple[ExtractionResult, datetime]]:
        """Devuelve (resultado, fecha del análisis) si ya se analizó, o None."""
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM analyses WHERE fingerprint = ? AND options_key = ?",
                (fingerprint, opts_key)).fetchone()
        if row is None:
            return None
        return self._row_to_result(row), datetime.fromisoformat(row["created_at"])

    def get(self, entry_id: int) -> Optional[tuple[ExtractionResult, str]]:
        """Devuelve (resultado, ruta original) de una entrada del historial."""
        with self._connect() as con:
            row = con.execute("SELECT * FROM analyses WHERE id = ?",
                              (entry_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_result(row), row["source_path"]

    def recent(self, limit: int = 500) -> list[HistoryEntry]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, filename, source_path, method, separated, key, "
                "       tempo_bpm, audio_duration, created_at, "
                "       json_array_length(chords_json) AS n "
                "FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            HistoryEntry(
                id=r["id"], filename=r["filename"], source_path=r["source_path"],
                method=r["method"], separated=bool(r["separated"]), key=r["key"],
                tempo_bpm=r["tempo_bpm"], chord_count=r["n"] or 0,
                audio_duration=r["audio_duration"] or 0.0,
                created_at=datetime.fromisoformat(r["created_at"]))
            for r in rows
        ]

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> ExtractionResult:
        chords = [ChordSegment(c["start"], c["end"], c["chord"])
                  for c in json.loads(row["chords_json"])]
        return ExtractionResult(
            source=row["filename"], method=row["method"],
            separated=bool(row["separated"]), key=row["key"],
            tempo_bpm=row["tempo_bpm"], chords=chords)

    # ------------------------------------------------------------- escritura
    def save(self, result: ExtractionResult, path: str, fingerprint: str,
             opts_key: str) -> None:
        duration = max((c.end for c in result.chords), default=0.0)
        chords_json = json.dumps([{"start": c.start, "end": c.end, "chord": c.chord}
                                  for c in result.chords])
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        # Si se reanaliza con las mismas opciones, la entrada se reemplaza.
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO analyses "
                "(fingerprint, options_key, source_path, filename, file_size, "
                " method, separated, key, tempo_bpm, audio_duration, chords_json, "
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (fingerprint, opts_key, os.path.abspath(path),
                 os.path.basename(path), size, result.method,
                 int(result.separated), result.key, result.tempo_bpm, duration,
                 chords_json, datetime.now().isoformat(timespec="seconds")))

    def delete(self, entry_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM analyses WHERE id = ?", (entry_id,))

    def clear(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM analyses")

    def count(self) -> int:
        with self._connect() as con:
            return con.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
