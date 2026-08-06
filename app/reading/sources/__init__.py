"""Contrato que cumple toda fuente de textos, y las fuentes concretas.

`ReadingSource` es un `Protocol` para que la ingesta dependa de la interfaz y no de Engoo:
sumar o reemplazar una fuente es escribir un archivo acá, sin tocar `ingest.py` ni el
repositorio. Importa porque la fuente es la parte más frágil del módulo — depende del HTML
de un tercero, que puede cambiar sin aviso.
"""

from typing import Protocol, runtime_checkable

from app.reading.model import ReadingText


@runtime_checkable
class ReadingSource(Protocol):
    """Contrato de una fuente de textos de lectura."""

    @property
    def name(self) -> str:
        """Identificador corto que se persiste en la columna `source` (p. ej. 'engoo')."""
        ...

    async def fetch(self) -> list[ReadingText]:
        """Devuelve los textos disponibles según la configuración de la fuente.

        No lanza si un artículo individual falla: lo omite y sigue. Solo propaga si no pudo
        obtener nada, para que la ingesta pueda distinguir "no hay nada nuevo" de "la fuente
        está caída".
        """
        ...
