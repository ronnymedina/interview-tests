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


@dataclass(frozen=True)
class StoredReadingText:
    """Un texto del catálogo junto con su id de base de datos.

    `ReadingText` no lleva id porque las fuentes producen textos que todavía no existen en la
    base. Una vez guardado, el id es lo que viaja al navegador y lo que permite recuperar el
    mismo texto al evaluar el audio, sin que el cliente mande el texto de referencia.
    """

    id: int
    text: ReadingText


@runtime_checkable
class ReadingTextStore(Protocol):
    """Contrato de persistencia que necesitan la ingesta y el servicio de lectura."""

    async def upsert_many(self, texts: list[ReadingText]) -> UpsertResult:
        """Inserta o actualiza por `source_url`. Idempotente: correrlo dos veces con los
        mismos textos no duplica filas."""
        ...

    async def count(self) -> int:
        """Cuántos textos hay en el catálogo."""
        ...

    async def random(self, max_level: int | None = None) -> StoredReadingText | None:
        """Un texto al azar del catálogo, o None si no hay ninguno que sirva.

        `max_level` es un tope, no un nivel exacto: pedir 5 puede devolver un 4. Los textos
        sin nivel quedan fuera al filtrar, porque "no sé el nivel" podría ser un 8.
        """
        ...

    async def get(self, reading_id: int) -> StoredReadingText | None:
        """El texto con ese id, o None si no existe."""
        ...


class PostgresReadingTextStore:
    """Adaptador Postgres de ReadingTextStore.

    Sigue el patrón del resto de los repositorios: abre una conexión por operación vía
    `storage.connect()` y no crea la tabla (de eso se encarga `init_schema()` o el init del
    contenedor). `created_at` lo pone Postgres por DEFAULT.
    """

    # Las columnas que hidratan un StoredReadingText. En una constante para que `random` y
    # `get` no puedan divergir: si una trajera una columna menos, `_to_stored` fallaría solo
    # en uno de los dos caminos.
    _COLUMNS = "id, source, source_url, title, level, category, published_at, body"

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

    async def random(self, max_level: int | None = None) -> StoredReadingText | None:
        """Una fila al azar, opcionalmente limitada por dificultad.

        `ORDER BY random()` escanea la tabla entera, lo que sería un problema con millones de
        filas pero es irrelevante con las decenas o pocos cientos que produce la ingesta. La
        alternativa (contar y elegir un offset) cuesta dos viajes y se desincroniza si la
        ingesta inserta entre medio. Si el catálogo creciera de verdad, esto pasa a
        TABLESAMPLE.

        `level <= %s` descarta también las filas con `level IS NULL`, que es lo que queremos:
        un texto de dificultad desconocida no cumple "5 o menos". El índice
        `reading_texts_level_idx` es el que sirve a esta comparación.
        """
        where = "" if max_level is None else "WHERE level <= %s"
        params = () if max_level is None else (max_level,)
        async with self._storage.connect() as conn:
            row = await (
                await conn.execute(
                    f"SELECT {self._COLUMNS} FROM reading_texts {where} "
                    "ORDER BY random() LIMIT 1",
                    params,
                )
            ).fetchone()
        return None if row is None else self._to_stored(row)

    async def get(self, reading_id: int) -> StoredReadingText | None:
        """El texto con ese id. Es lo que permite reconstruir el extracto al evaluar."""
        async with self._storage.connect() as conn:
            row = await (
                await conn.execute(
                    f"SELECT {self._COLUMNS} FROM reading_texts WHERE id = %s", (reading_id,)
                )
            ).fetchone()
        return None if row is None else self._to_stored(row)

    @staticmethod
    def _to_stored(row) -> StoredReadingText:
        return StoredReadingText(
            id=row["id"],
            text=ReadingText(
                source=row["source"],
                source_url=row["source_url"],
                title=row["title"],
                body=row["body"],
                level=row["level"],
                category=row["category"],
                published_at=row["published_at"],
            ),
        )
