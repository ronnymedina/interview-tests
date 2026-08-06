"""El texto de lectura tal como lo maneja el módulo, independiente de la fuente y del SQL.

Es lo que devuelven las fuentes (`sources/`) y lo que consume el repositorio. Que sea una
dataclass plana, sin métodos ni dependencias, es lo que permite probar el parser de una
fuente sin base de datos y el repositorio sin red.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadingText:
    """Un artículo del catálogo, guardado completo e intacto.

    El recorte al extracto que se lee en voz alta se calcula al servir, nunca al ingerir:
    así funcionalidades futuras (un plan sobre el texto entero, búsqueda semántica) tienen
    el dato completo sin volver a scrapear.
    """

    source: str
    source_url: str
    title: str
    body: str
    # Nullable a propósito: "no conozco el nivel" y "nivel 0" son cosas distintas, y un
    # cero inventado ensuciaría el filtro por rango cuando se sirva por dificultad.
    level: int | None = None
    category: str = ""
    published_at: str = ""

    @property
    def word_count(self) -> int:
        """Palabras del cuerpo. Derivado, nunca persistido: un campo derivado que se guarda
        es un campo que puede desincronizarse del texto."""
        return len(self.body.split())
