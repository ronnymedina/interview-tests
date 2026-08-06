"""Persistencia del catálogo de textos.

`ReadingTextStore` es el contrato que consume la ingesta; `PostgresReadingTextStore` es su
adaptador Postgres. Es un `Protocol` por la misma razón que en `app/limits`: la ingesta
depende de la interfaz, y en los tests se inyecta un doble en memoria sin levantar una base.

Todo es asíncrono porque la ingesta corre dentro del event loop, tanto en el script como en
la tarea periódica del servidor.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.reading.model import ReadingText
from app.storage import AsyncPostgresStorage


@dataclass(frozen=True)
class UpsertResult:
    """Cuántas filas se crearon y cuántas se actualizaron en una corrida."""

    inserted: int
    updated: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated


@runtime_checkable
class ReadingTextStore(Protocol):
    """Contrato de persistencia que necesita la ingesta."""

    async def upsert_many(self, texts: list[ReadingText]) -> UpsertResult:
        """Inserta o actualiza por `source_url`. Idempotente: correrlo dos veces con los
        mismos textos no duplica filas."""
        ...

    async def count(self) -> int:
        """Cuántos textos hay en el catálogo."""
        ...


class PostgresReadingTextStore:
    """Adaptador Postgres de ReadingTextStore.

    Sigue el patrón del resto de los repositorios: abre una conexión por operación vía
    `storage.connect()` y no crea la tabla (de eso se encarga `init_schema()` o el init del
    contenedor). `created_at` lo pone Postgres por DEFAULT.
    """

    def __init__(self, storage: AsyncPostgresStorage) -> None:
        self._storage = storage

    async def upsert_many(self, texts: list[ReadingText]) -> UpsertResult:
        """Todos los textos de una corrida van en una sola transacción.

        Si el artículo 7 falla, se revierten los 6 anteriores y el catálogo queda como
        estaba, en vez de a medio poblar. Para un job idempotente que reintenta al día
        siguiente, eso es preferible a un estado parcial.

        `xmax = 0` distingue inserción de actualización: en la fila devuelta por un INSERT
        nuevo, `xmax` vale 0; si el ON CONFLICT terminó actualizando, trae el id de la
        transacción que la bloqueó. Es la forma habitual de contar ambos casos con un solo
        viaje por fila.
        """
        if not texts:
            return UpsertResult(inserted=0, updated=0)

        inserted = 0
        updated = 0
        async with self._storage.connect() as conn:
            for text in texts:
                row = await (
                    await conn.execute(
                        "INSERT INTO reading_texts "
                        "(source, source_url, title, level, category, published_at, body) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (source_url) DO UPDATE SET "
                        "title = EXCLUDED.title, level = EXCLUDED.level, "
                        "category = EXCLUDED.category, published_at = EXCLUDED.published_at, "
                        "body = EXCLUDED.body, updated_at = now() "
                        "RETURNING (xmax = 0) AS inserted",
                        (
                            text.source,
                            text.source_url,
                            text.title,
                            text.level,
                            text.category,
                            text.published_at,
                            text.body,
                        ),
                    )
                ).fetchone()
                assert row is not None  # RETURNING siempre devuelve la fila afectada
                if row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
        return UpsertResult(inserted=inserted, updated=updated)

    async def count(self) -> int:
        async with self._storage.connect() as conn:
            row = await (
                await conn.execute("SELECT COUNT(*) AS n FROM reading_texts")
            ).fetchone()
        assert row is not None  # agregado sin GROUP BY siempre devuelve una fila
        return int(row["n"])
