"""Servicio de evaluación de pronunciación como unidad inyectable.

Compone la cola de scoring (`TurnScoring`) con la función de evaluación de Azure. El
endpoint encola el audio de cada respuesta con `score_answer` (no espera) y pide el agregado
al final con `final_pronunciation`. La construcción real (`build_speech_service`) lee la
config y arma un cliente de Azure; en tests se inyecta una `assess_fn` falsa.
"""

import os
import tempfile
from collections.abc import Callable

from app.speech.assessment import SpeechError, assess_unscripted
from app.speech.azure_client import AzureSpeechClient
from app.speech.scoring import TurnScoring
from config import settings

__all__ = ["SpeechError", "SpeechService", "build_speech_service"]


class SpeechService:
    """Orquesta la evaluación diferida de pronunciación por conversación."""

    def __init__(self, assess_fn: Callable[[bytes], dict | None]) -> None:
        self._scoring = TurnScoring(assess_fn=assess_fn)

    def score_answer(self, conversation_id: str, audio_bytes: bytes) -> None:
        """Encola la evaluación del audio de una respuesta en segundo plano (no espera)."""
        self._scoring.enqueue(conversation_id, audio_bytes)

    def final_pronunciation(self, conversation_id: str) -> dict:
        """Recoge y agrega los scores/palabras/segundos de todos los turnos de la conversación."""
        results = self._scoring.collect(conversation_id)
        return self._scoring.aggregate(results)


def _assess_with_client(client: AzureSpeechClient) -> Callable[[bytes], dict | None]:
    """Devuelve una assess_fn que escribe el audio a un WAV temporal y llama a Azure.

    Un turno sin voz o un error de Azure no debe romper el resultado final: se descarta ese
    turno devolviendo None.
    """

    def assess(audio_bytes: bytes) -> dict | None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = tmp.name
        try:
            return assess_unscripted(wav_path, client=client)
        except SpeechError:
            return None
        finally:
            os.unlink(wav_path)

    return assess


def build_speech_service() -> SpeechService | None:
    """Arma el servicio desde config; devuelve None si falta la clave de Azure (degradación).

    Así la conversación funciona igual sin Azure (transcripción del navegador + feedback de
    Gemini); solo se omite el scoring de pronunciación.
    """
    if not settings.AZURE_SPEECH_KEY:
        return None
    client = AzureSpeechClient(
        settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION, settings.SPEECH_LANGUAGE
    )
    return SpeechService(assess_fn=_assess_with_client(client))
