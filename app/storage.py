"""Adaptador de almacenamiento Postgres.

Envuelve la creación de conexiones para que los repositorios reciban esto por
inyección de dependencia y no sepan dónde ni cómo se abre la base. Se instancia
una vez (en `main`, con `settings.DATABASE_URL`) y se inyecta a cada repositorio.

No define ni crea el esquema: de eso se encarga Alembic (ver `app/schema.py`).
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import cast

import psycopg
from psycopg.rows import DictRow, dict_row


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
        conn = cast(
            "psycopg.Connection[DictRow]",
            psycopg.connect(self._dsn, row_factory=dict_row),
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


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
        conn = await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row)
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.close()
