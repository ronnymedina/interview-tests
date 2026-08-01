"""Cola en segundo plano para evaluar la pronunciación de las respuestas por conversación.

Aísla la acumulación de resultados de la evaluación por conversación: el endpoint encola el
audio de cada turno y NO espera; al final se recogen y agregan. Todo vive en memoria del
proceso (consistente con el checkpointer del grafo). Migrado del legacy scoring.py, ahora
como clase inyectable (recibe la función de evaluación) en vez de módulo global.
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


class TurnScoring:
    """Acumula la evaluación de cada respuesta en segundo plano y la agrega al final.

    Recibe `assess_fn`, que evalúa unos bytes de audio y devuelve el dict de la evaluación o
    None si no se pudo (sin voz, error de Azure): ese turno se descarta sin romper el total.
    """

    def __init__(self, assess_fn: Callable[[bytes], dict | None], max_workers: int = 4) -> None:
        self._assess_fn = assess_fn
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._pending: dict[str, list[Future]] = {}

    def enqueue(self, conversation_id: str, audio_bytes: bytes) -> Future:
        """Lanza la evaluación del audio en segundo plano y la registra en la conversación."""
        future = self._executor.submit(self._assess_fn, audio_bytes)
        with self._lock:
            self._pending.setdefault(conversation_id, []).append(future)
        return future

    def collect(self, conversation_id: str) -> list[dict]:
        """Espera y devuelve los resultados de todos los turnos encolados (descarta los None)."""
        with self._lock:
            futures = self._pending.pop(conversation_id, [])
        results = [future.result() for future in futures]
        return [result for result in results if result is not None]

    def aggregate(self, results: list[dict]) -> dict:
        """Promedia los scores de todos los turnos, concatena palabras y suma la duración."""
        scores = self._aggregate_scores([result["scores"] for result in results])
        words = [word for result in results for word in result["words"]]
        audio_seconds = round(sum(result["audio_seconds"] for result in results), 3)
        return {"scores": scores, "words": words, "audio_seconds": audio_seconds}

    @staticmethod
    def _aggregate_scores(per_turn_scores: list[dict]) -> dict:
        """Promedia por dimensión, ignorando None (ej. prosody no soportada)."""

        def avg(key: str):
            values = [s[key] for s in per_turn_scores if s.get(key) is not None]
            return round(sum(values) / len(values), 1) if values else None

        return {
            "pronunciation": avg("pronunciation"),
            "accuracy": avg("accuracy"),
            "fluency": avg("fluency"),
            "prosody": avg("prosody"),
        }
