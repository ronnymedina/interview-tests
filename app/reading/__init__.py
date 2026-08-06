"""Práctica de lectura: catálogo de textos reales para leer en voz alta.

El flujo tiene dos mitades. La ingesta: `sources/` (obtiene) → `ingest` (orquesta) →
`repository` (persiste), que `scheduler` repite cada N horas dentro del servidor. Y el
servicio: `service` → `excerpt` + `app/speech`, que entrega un texto al azar ya recortado y
evalúa la lectura contra ese mismo texto.

El extracto nunca se persiste ni se cachea: se recalcula desde el cuerpo guardado cada vez
que hace falta, porque `make_excerpt` es determinista.
"""

from app.reading.model import ReadingText
from app.reading.service import ReadingError, ReadingService, build_reading_service

__all__ = ["ReadingText", "ReadingError", "ReadingService", "build_reading_service"]
