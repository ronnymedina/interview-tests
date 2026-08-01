"""Adaptador de almacenamiento Postgres.

Envuelve la creación de conexiones para que los repositorios reciban esto por
inyección de dependencia y no sepan dónde ni cómo se abre la base. Se instancia
una vez (en `main`, con `config.DATABASE_URL`) y se inyecta a cada repositorio.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

import psycopg
from psycopg.rows import DictRow, dict_row

# DDL de la tabla que persiste las configuraciones de conversación. Es la misma
# definición que usa el script de init del contenedor Postgres (docker-compose);
# se expone acá para poder crear el esquema desde código en un entorno standalone.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_configs (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    name         TEXT NOT NULL,
    user_context TEXT NOT NULL
);
"""


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
        """Crea la tabla `conversation_configs` si no existe (uso standalone, sin compose)."""
        with self.connect() as conn:
            conn.execute(_SCHEMA)
