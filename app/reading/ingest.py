"""Orquesta fuentes → repositorio, y es ejecutable a mano.

    python -m app.reading.ingest

La misma `run_ingest` la usa la tarea periódica del servidor (`scheduler.py`). No hay dos
implementaciones: correrlo a mano y correrlo solo hacen exactamente lo mismo, así lo que
probás en desarrollo es lo que va a pasar en producción.
"""

import asyncio
from dataclasses import dataclass

import structlog

from app.logconfig import configure_logging
from app.reading.repository import PostgresReadingTextStore, ReadingTextStore
from app.reading.sources import ReadingSource
from app.reading.sources.engoo import EngooSource
from app.storage import AsyncPostgresStorage
from config import settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestResult:
    """Qué pasó en una corrida. `fetched` puede ser mayor que `inserted + updated` si la
    fuente devolvió textos repetidos entre categorías."""

    fetched: int
    inserted: int
    updated: int

    def describe(self) -> str:
        return (
            f"{self.fetched} artículos obtenidos, "
            f"{self.inserted} nuevos, {self.updated} actualizados"
        )


async def run_ingest(source: ReadingSource, store: ReadingTextStore) -> IngestResult:
    """Baja los textos de una fuente y los guarda. No captura errores de la fuente.

    Si la fuente falla entera, la excepción sube: quien llama decide qué hacer. El script
    corta con código de salida distinto de cero, y el scheduler loguea y sigue vivo para la
    corrida siguiente.
    """
    texts = await source.fetch()
    result = await store.upsert_many(texts)
    logger.info(
        "ingesta_terminada",
        fuente=source.name,
        obtenidos=len(texts),
        nuevos=result.inserted,
        actualizados=result.updated,
    )
    return IngestResult(
        fetched=len(texts), inserted=result.inserted, updated=result.updated
    )


def build_default_ingest() -> tuple[ReadingSource, ReadingTextStore]:
    """Arma la fuente y el repositorio que se usan de verdad (fuera de los tests)."""
    storage = AsyncPostgresStorage(settings.DATABASE_URL)
    return EngooSource(), PostgresReadingTextStore(storage)


async def main() -> None:
    configure_logging()
    source, store = build_default_ingest()
    before = await store.count()
    result = await run_ingest(source, store)
    after = await store.count()
    print(
        f"Ingesta terminada: {result.describe()}. "
        f"Catálogo: {before} → {after} textos."
    )


if __name__ == "__main__":
    asyncio.run(main())
