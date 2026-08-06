"""Orquestación de la práctica de lectura: catálogo + recorte + evaluación de Azure.

La decisión central vive acá: al evaluar, el texto de referencia se RECALCULA desde la base
a partir del `reading_id`. No lo manda el cliente (podría inventarlo y sacar 100 siempre) ni
se guarda en una caché en memoria (moriría en cada redeploy y no se compartiría entre
workers). `make_excerpt` es determinista, así que releer la fila devuelve exactamente el
mismo texto que se le mostró al usuario.
"""

import asyncio
import os
import tempfile
from collections.abc import Callable

from config import settings
from app.reading.excerpt import make_excerpt
from app.reading.repository import PostgresReadingTextStore, ReadingTextStore
from app.speech.assessment import SpeechError, assess_scripted
from app.storage import AsyncPostgresStorage


class ReadingError(Exception):
    """Error pensado para mostrarse tal cual al usuario. `status` es el código HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class ReadingService:
    """Entrega textos del catálogo y evalúa la lectura contra el texto entregado."""

    def __init__(
        self,
        store: ReadingTextStore,
        assess_fn: Callable[[str, str], dict] | None = None,
    ) -> None:
        self._store = store
        # Inyectable para probar sin red; en producción es assess_scripted contra Azure.
        self._assess_fn = assess_fn or assess_scripted

    async def random_excerpt(self) -> dict:
        """Un texto al azar del catálogo, ya recortado al fragmento que se lee en voz alta."""
        stored = await self._store.random()
        if stored is None:
            raise ReadingError(
                "Todavía no hay textos para leer. Corre la ingesta del catálogo "
                "(`python -m app.reading.ingest`) e intenta de nuevo.",
                status=503,
            )
        excerpt = make_excerpt(stored.text.body, settings.READING_MAX_WORDS)
        return {
            "reading_id": stored.id,
            "title": stored.text.title,
            "level": stored.text.level,
            "source_url": stored.text.source_url,
            "excerpt": excerpt,
            "word_count": len(excerpt.split()),
        }

    async def assess(self, reading_id: int, audio_bytes: bytes) -> dict:
        """Evalúa el audio contra el extracto de `reading_id`, releído de la base."""
        stored = await self._store.get(reading_id)
        if stored is None:
            raise ReadingError("Ese texto ya no existe en el catálogo.", status=404)

        reference_text = make_excerpt(stored.text.body, settings.READING_MAX_WORDS)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = tmp.name
        try:
            # El SDK de Azure es bloqueante: fuera del event loop, o frena a todos los demás.
            result = await asyncio.to_thread(self._assess_fn, wav_path, reference_text)
        except SpeechError as error:
            # Se traduce en vez de dejarla salir: el endpoint sólo conoce ReadingError, y sin
            # esto un 502 de Azure o un 422 de "no se detectó voz" llegarían al usuario como
            # un 500 genérico.
            raise ReadingError(str(error), status=error.status)
        finally:
            os.unlink(wav_path)

        # Viaja de vuelta para que la página pinte las omisiones sobre el texto real sin
        # tener que confiar en la copia que tenga el navegador.
        result["reference_text"] = reference_text
        return result


def build_reading_service(storage: AsyncPostgresStorage) -> ReadingService:
    """Arma el servicio con el repositorio Postgres real. Se llama una vez, en el servidor."""
    return ReadingService(PostgresReadingTextStore(storage))
