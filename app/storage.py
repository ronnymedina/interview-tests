"""Adaptador de almacenamiento Postgres.

Envuelve la creación de conexiones para que los repositorios reciban esto por
inyección de dependencia y no sepan dónde ni cómo se abre la base. Se instancia
una vez (en `main`, con `settings.DATABASE_URL`) y se inyecta a cada repositorio.
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import LiteralString, cast

import psycopg
from psycopg.rows import DictRow, dict_row

# DDL de las tablas de app/. Es la misma definición que usan los scripts de init del
# contenedor Postgres (docker/initdb/*.sql); se expone acá para poder crear el esquema
# desde código en un entorno standalone. Una sentencia por elemento (psycopg ejecuta una
# sentencia por llamada a execute).
_SCHEMA: tuple[LiteralString, ...] = (
    """
    CREATE TABLE IF NOT EXISTS conversation_configs (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        name         TEXT NOT NULL,
        user_context TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_events (
        id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id         TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        provider        TEXT NOT NULL,
        kind            TEXT NOT NULL,
        input_tokens    INTEGER NOT NULL DEFAULT 0,
        output_tokens   INTEGER NOT NULL DEFAULT 0,
        audio_seconds   REAL NOT NULL DEFAULT 0,
        cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_starts (
        id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id         TEXT NOT NULL,
        conversation_id TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS pilot_feedback (
        id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id       TEXT NOT NULL,
        liked         BOOLEAN,
        rating        INTEGER,
        comment       TEXT NOT NULL DEFAULT '',
        wants_more    BOOLEAN,
        suggestions   TEXT NOT NULL DEFAULT ''
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reading_texts (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        source       TEXT NOT NULL,
        source_url   TEXT NOT NULL UNIQUE,
        title        TEXT NOT NULL,
        level        INTEGER,
        category     TEXT NOT NULL DEFAULT '',
        published_at TEXT NOT NULL DEFAULT '',
        body         TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS reading_texts_level_idx ON reading_texts (level);
    """,
)


class PostgresStorage:
    """Fábrica de conexiones Postgres envuelta como context manager."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def connect(self) -> Generator[psycopg.Connection[DictRow], None, None]:
        """Abre una conexión nueva, la entrega, y al salir hace commit/rollback y la cierra.

        Devuelve un contexto NUEVO en cada llamada (no reutiliza una conexión de instancia),
        así dos operaciones en paralelo no se pisan la misma conexión. Las filas salen como
        dict (`dict_row`), así el repositorio accede por nombre de columna (`row["col"]`).
        """
        # cast + ignore: los stubs de psycopg no resuelven bien el overload de
        # `connect(..., row_factory=dict_row)`, aunque en runtime devuelve DictRow.
        conn = cast(
            "psycopg.Connection[DictRow]",
            psycopg.connect(self._dsn, row_factory=dict_row),  # type: ignore[call-overload]
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Crea las tablas de app/ si no existen (uso standalone, sin compose)."""
        with self.connect() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)


class AsyncPostgresStorage:
    """Gemelo asíncrono de PostgresStorage, sobre el mismo psycopg 3.

    psycopg 3 trae asyncio nativo (`AsyncConnection`), así que no hace falta un segundo
    driver: es la misma librería, el mismo dialecto de parámetros y el mismo `dict_row`.

    Existe porque `app/reading` corre dentro del event loop (el script de ingesta y la tarea
    periódica del servidor), y ahí una conexión bloqueante frenaría todo lo demás. Convive
    con la versión sincrónica, que sigue sirviendo a los repositorios ya migrados; cuando
    esos pasen a async, esta queda como única.

    No usa pool a propósito: la ingesta abre una conexión por corrida y la cierra. Un pool
    tendría sentido si esto atendiera requests.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[psycopg.AsyncConnection[DictRow], None]:
        """Abre una conexión nueva, la entrega, y al salir hace commit/rollback y la cierra.

        El `finally` con `close()` no es decorativo: psycopg 3 abre una transacción con el
        primer `execute` (no está en autocommit), incluso si es un SELECT. Sin el cierre,
        una excepción dejaría la conexión colgada e *idle in transaction* del lado del
        servidor, reteniendo snapshots. En la tarea periódica, que vive días, cada fallo
        filtraría una conexión.
        """
        # Mismo cast + ignore que en la versión sincrónica: los stubs de psycopg no
        # resuelven el overload de `connect(..., row_factory=dict_row)`.
        raw = await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)  # type: ignore[call-overload]
        conn = cast("psycopg.AsyncConnection[DictRow]", raw)
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()

    async def init_schema(self) -> None:
        """Crea las tablas de app/ si no existen (uso standalone, sin compose)."""
        async with self.connect() as conn:
            for statement in _SCHEMA:
                await conn.execute(statement)
