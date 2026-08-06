"""Práctica de lectura: catálogo de textos reales para leer en voz alta.

Esta fase cubre solo la ingesta: bajar artículos de una fuente externa y guardarlos en
`reading_texts`. Los endpoints, el recorte a extracto y la evaluación contra el texto de
referencia llegan después, cuando haya catálogo con qué probarlos.

El flujo es `sources/` (obtiene) → `ingest` (orquesta) → `repository` (persiste), y
`scheduler` lo repite cada N horas dentro del servidor.
"""

from app.reading.model import ReadingText

__all__ = ["ReadingText"]
