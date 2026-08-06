"""Tarea de fondo que repite la ingesta cada N horas dentro del servidor.

Es un envoltorio delgado sobre `run_ingest`: no reimplementa nada, solo decide *cuándo*
correrla y se traga los errores para que una caída de la fuente no tumbe el servidor.

La primera corrida se hace solo si el catálogo está vacío. Sin esa condición, reiniciar el
servidor en desarrollo saldría a scrapear cada vez, que es maltratar a la fuente para
obtener contenido que ya se tiene.
"""

import asyncio
import structlog

from config import settings
from app.reading.ingest import run_ingest
from app.reading.repository import ReadingTextStore
from app.reading.sources import ReadingSource

logger = structlog.get_logger(__name__)


async def _ingest_guarded(source: ReadingSource, store: ReadingTextStore) -> None:
    """Corre la ingesta sin dejar escapar excepciones.

    `CancelledError` sí se propaga: es cómo el apagado del servidor pide que la tarea
    termine, y tragárselo dejaría el shutdown colgado.
    """
    try:
        await run_ingest(source, store)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "ingesta_fallida", detalle="Se reintenta en el próximo ciclo."
        )


async def ingest_loop(source: ReadingSource, store: ReadingTextStore) -> None:
    """Ingesta al arrancar si el catálogo está vacío, y después cada N horas."""
    interval = settings.READING_INGEST_INTERVAL_HOURS * 3600
    try:
        catalog_size = await store.count()
    except Exception:
        logger.exception(
            "catalogo_inconsultable", detalle="Se omite la ingesta inicial."
        )
        catalog_size = -1

    if catalog_size == 0:
        logger.info("catalogo_vacio", detalle="Se ingiere al arrancar.")
        await _ingest_guarded(source, store)

    while True:
        await asyncio.sleep(interval)
        await _ingest_guarded(source, store)
