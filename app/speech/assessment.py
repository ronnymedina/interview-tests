"""Lógica de evaluación de pronunciación de habla libre (unscripted).

Pide a Azure la evaluación a través de `AzureSpeechClient` y transforma el resultado crudo
en el dict normalizado que consume la página. No habla directamente con el SDK: toda la
conexión vive en azure_client.py. Migrado del legacy speech.py (solo el modo unscripted),
con un campo extra `audio_seconds` para el cálculo de costo de Azure.
"""

import config
from app.speech.azure_client import AzureSpeechClient, AzureSpeechError

# 1 segundo = 10_000_000 unidades de 100 ns (ticks) de Azure.
_TICKS_PER_SECOND = 10_000_000


class SpeechError(Exception):
    """Error pensado para mostrarse tal cual al usuario. `status` es el código HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def assess_unscripted(wav_path: str, client: AzureSpeechClient | None = None) -> dict:
    """Evalúa la pronunciación de un WAV SIN texto de referencia (habla libre).

    Azure reconoce lo dicho y puntúa accuracy/fluency/prosody; no hay completeness (requiere
    referencia). El texto reconocido sirve además como la transcripción de lo que dijo el
    usuario. `client` permite inyectar un doble en los tests.
    """
    if not config.AZURE_SPEECH_KEY:
        raise SpeechError(
            "Falta AZURE_SPEECH_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Azure.",
            status=500,
        )

    if client is None:
        client = AzureSpeechClient(
            config.AZURE_SPEECH_KEY, config.AZURE_SPEECH_REGION, config.SPEECH_LANGUAGE
        )

    try:
        state = client.recognize(wav_path, "")
    except AzureSpeechError as error:
        raise SpeechError(f"Azure canceló la petición: {error}", status=502)

    if not state["words"]:
        raise SpeechError(
            "No se detectó voz en el audio. Revisa el micrófono e intenta de nuevo.",
            status=422,
        )

    return _aggregate_unscripted(state)


def _aggregate_unscripted(state: dict) -> dict:
    """Combina los segmentos en un resultado sin referencia (sin completeness ni miscue)."""
    words = list(state["words"])

    # Accuracy por debajo de 60 sin otro error = mala pronunciación.
    for word in words:
        if word.error_type == "None" and word.accuracy_score < 60:
            word._error_type = "Mispronunciation"

    accuracy = sum(w.accuracy_score for w in words) / len(words)

    prosody = (
        sum(state["prosody_scores"]) / len(state["prosody_scores"])
        if state["prosody_scores"]
        else None
    )

    span = state["end_offset"] - state["start_offset"]
    fluency = sum(state["durations"]) / span * 100 if span > 0 else 0.0

    if prosody is not None:
        ordered = sorted([accuracy, fluency, prosody])
        pronunciation = ordered[0] * 0.6 + ordered[1] * 0.2 + ordered[2] * 0.2
    else:
        ordered = sorted([accuracy, fluency])
        pronunciation = ordered[0] * 0.6 + ordered[1] * 0.4

    return {
        "recognized_text": " ".join(state["texts"]),
        "scores": {
            "pronunciation": round(pronunciation, 1),
            "accuracy": round(accuracy, 1),
            "fluency": round(fluency, 1),
            "completeness": None,
            "prosody": round(prosody, 1) if prosody is not None else None,
        },
        "words": [AzureSpeechClient.word_to_dict(w) for w in words],
        "audio_seconds": round(max(0, span) / _TICKS_PER_SECOND, 3),
    }
