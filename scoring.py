"""Cola en memoria para evaluar la pronunciacion de las respuestas en segundo plano.

Aisla la acumulacion de resultados de speech.assess_unscripted por conversacion. En modo
navegador el endpoint encola el audio y no espera; en modo Azure espera el resultado del
turno para mostrar su score, pero igual queda acumulado para el agregado final. Todo vive
en memoria del proceso (consistente con el checkpointer del grafo).
"""

import os
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import speech

_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()
_pending: dict[str, list[Future]] = {}


def _assess(audio_bytes: bytes) -> dict | None:
    """Evalua un WAV; devuelve el result de assess_unscripted o None si Azure fallo.

    Una respuesta sin voz o un error de Azure no debe romper el resultado final: se
    descarta ese turno del scoring.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        wav_path = tmp.name
    try:
        return speech.assess_unscripted(wav_path)
    except speech.SpeechError:
        return None
    finally:
        os.unlink(wav_path)


def enqueue(conversation_id: str, audio_bytes: bytes) -> Future:
    """Lanza la evaluacion del audio en segundo plano y la registra en la conversacion."""
    future = _executor.submit(_assess, audio_bytes)
    with _lock:
        _pending.setdefault(conversation_id, []).append(future)
    return future


def collect(conversation_id: str) -> list[dict]:
    """Espera y devuelve los resultados de todos los turnos encolados (descarta los None)."""
    with _lock:
        futures = _pending.pop(conversation_id, [])
    results = [future.result() for future in futures]
    return [result for result in results if result is not None]


def aggregate(results: list[dict]) -> tuple[dict, list[dict]]:
    """Promedia los scores de todos los turnos y concatena sus palabras."""
    scores = _aggregate_scores([result["scores"] for result in results])
    words = [word for result in results for word in result["words"]]
    return scores, words


def _aggregate_scores(per_turn_scores: list[dict]) -> dict:
    """Promedia por dimension, ignorando None (ej. prosody no soportada)."""

    def avg(key: str):
        values = [s[key] for s in per_turn_scores if s.get(key) is not None]
        return round(sum(values) / len(values), 1) if values else None

    return {
        "pronunciation": avg("pronunciation"),
        "accuracy": avg("accuracy"),
        "fluency": avg("fluency"),
        "prosody": avg("prosody"),
    }
