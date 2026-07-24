"""Historial de intentos en sqlite."""

import json
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
-- Textos guardados que el usuario practica una y otra vez.
CREATE TABLE IF NOT EXISTS texts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    difficulty  INTEGER          -- 1..10, NULL si no se indica
);

CREATE TABLE IF NOT EXISTS attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    text_id             INTEGER NOT NULL,
    reference_text      TEXT NOT NULL,
    recognized_text     TEXT NOT NULL,
    pronunciation_score REAL,
    accuracy_score      REAL,
    fluency_score       REAL,
    completeness_score  REAL,
    prosody_score       REAL,
    result_json         TEXT NOT NULL
);

-- Una fila por cada palabra de cada intento, para poder ver el historial por palabra
-- (que palabras mejoras y cuales fallas) agregado entre todos los intentos.
CREATE TABLE IF NOT EXISTS word_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    word        TEXT NOT NULL,   -- en minuscula, para agrupar
    accuracy    REAL,            -- NULL si la palabra se omitio (no se pronuncio)
    error_type  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_word_scores_word ON word_scores (word);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        # Reset de una sola vez: si existe una tabla attempts del esquema viejo (sin
        # text_id), se descarta junto a word_scores. No hay migracion de datos.
        _drop_legacy_tables(conn)
        conn.executescript(SCHEMA)


def _drop_legacy_tables(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'attempts'"
    ).fetchone()
    if not exists:
        return
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(attempts)")}
    if "text_id" not in columns:
        conn.executescript("DROP TABLE IF EXISTS word_scores; DROP TABLE IF EXISTS attempts;")


# --- textos guardados --------------------------------------------------------


def create_text(title: str, content: str, difficulty: int | None) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO texts (created_at, updated_at, title, content, difficulty) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, now, title, content, difficulty),
        )
        return cursor.lastrowid or 0


def update_text(text_id: int, title: str, content: str, difficulty: int | None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE texts SET title = ?, content = ?, difficulty = ?, updated_at = ? "
            "WHERE id = ?",
            (title, content, difficulty, now, text_id),
        )


def delete_text(text_id: int) -> None:
    """Borra el texto y, en cascada, sus intentos y las palabras de esos intentos."""
    with _connect() as conn:
        conn.execute(
            "DELETE FROM word_scores WHERE attempt_id IN "
            "(SELECT id FROM attempts WHERE text_id = ?)",
            (text_id,),
        )
        conn.execute("DELETE FROM attempts WHERE text_id = ?", (text_id,))
        conn.execute("DELETE FROM texts WHERE id = ?", (text_id,))


def get_text(text_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, updated_at, title, content, difficulty "
            "FROM texts WHERE id = ?",
            (text_id,),
        ).fetchone()
        return dict(row) if row else None


def list_texts() -> list[dict]:
    """Todos los textos con cuantas veces se practicaron y su score promedio."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                t.id, t.title, t.content, t.difficulty, t.created_at, t.updated_at,
                COUNT(a.id)              AS times,
                AVG(a.pronunciation_score) AS avg_pronunciation
            FROM texts t
            LEFT JOIN attempts a ON a.text_id = t.id
            GROUP BY t.id
            ORDER BY t.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def save_attempt(text_id: int, result: dict) -> int:
    """Guarda un intento ligado a un texto. `result` es el dict de speech.assess().

    Guarda el contenido del texto como snapshot en reference_text, para que editar el
    texto despues no cambie el significado de los intentos viejos.
    """
    scores = result["scores"]
    text = get_text(text_id)
    reference_text = text["content"] if text else ""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO attempts (
                created_at, text_id, reference_text, recognized_text,
                pronunciation_score, accuracy_score, fluency_score,
                completeness_score, prosody_score, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                text_id,
                reference_text,
                result["recognized_text"],
                scores["pronunciation"],
                scores["accuracy"],
                scores["fluency"],
                scores["completeness"],
                scores["prosody"],
                # Guardamos el detalle completo para poder revisar un intento viejo
                # sin tener que cambiar el esquema de la tabla.
                json.dumps(result, ensure_ascii=False),
            ),
        )
        attempt_id = cursor.lastrowid or 0
        _save_words(conn, attempt_id, now, result["words"])
        return attempt_id


def _save_words(conn, attempt_id: int, created_at: str, words: list[dict]) -> None:
    """Guarda cada palabra del intento en word_scores para el banco de palabras.

    Las inserciones (palabras dichas que no estaban en la lectura) se ignoran: no son
    vocabulario a mejorar. Las omisiones se guardan con accuracy NULL (no se pronuncio).
    """
    rows = []
    for word in words:
        if word["error_type"] == "Insertion":
            continue
        accuracy = None if word["error_type"] == "Omission" else word["accuracy"]
        rows.append((attempt_id, created_at, word["word"].lower(), accuracy, word["error_type"]))
    conn.executemany(
        "INSERT INTO word_scores (attempt_id, created_at, word, accuracy, error_type) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def list_attempts(limit: int = 20) -> list[dict]:
    """Cabeceras de los ultimos intentos, sin el detalle de palabras."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, reference_text, recognized_text,
                   pronunciation_score, accuracy_score, fluency_score,
                   completeness_score, prosody_score
            FROM attempts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_word_stats(limit: int = 200) -> list[dict]:
    """Historial por palabra: agrega todos los intentos y ordena de peor a mejor.

    Para cada palabra devuelve cuantas veces la practicaste, su promedio, el mejor y peor
    score, cuantas veces la fallaste (score < 80) y cuantas la saltaste (omision).
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                word,
                COUNT(*)                                                   AS times,
                AVG(accuracy)                                             AS avg_accuracy,
                MIN(accuracy)                                            AS worst_accuracy,
                MAX(accuracy)                                             AS best_accuracy,
                MAX(created_at)                                          AS last_seen,
                SUM(CASE WHEN error_type = 'Omission' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN accuracy IS NOT NULL AND accuracy < 80
                         THEN 1 ELSE 0 END)                              AS failed
            FROM word_scores
            GROUP BY word
            -- Las nunca pronunciadas (promedio NULL) y las de peor score van primero.
            ORDER BY COALESCE(AVG(accuracy), -1) ASC, times DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_word_history(word: str) -> list[dict]:
    """Todos los intentos de una palabra concreta, del mas viejo al mas nuevo.

    Sirve para ver como fue evolucionando su score intento tras intento.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT created_at, accuracy, error_type
            FROM word_scores
            WHERE word = ?
            ORDER BY created_at ASC, id ASC
            """,
            (word.lower(),),
        ).fetchall()
        return [dict(row) for row in rows]
