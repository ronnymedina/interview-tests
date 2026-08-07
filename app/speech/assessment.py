"""Lógica de evaluación de pronunciación, en sus dos modos.

Pide a Azure la evaluación a través de `AzureSpeechClient` y transforma el resultado crudo
en el dict normalizado que consume la página. No habla directamente con el SDK: toda la
conexión vive en azure_client.py. Migrado del legacy speech.py, con un campo extra
`audio_seconds` en los dos modos para el cálculo de costo de Azure.

`assess_unscripted` es habla libre (la conversación): no hay texto previo con qué comparar,
así que no hay completeness ni miscue. `assess_scripted` evalúa contra un texto de referencia
(la práctica de lectura), y ahí sí aparecen completeness y las omisiones/inserciones, que es
justamente la señal que importa cuando el usuario lee algo escrito.
"""

import difflib
import string

from app.speech.azure_client import AzureSpeechClient, AzureSpeechError
from config import settings

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
    if not settings.AZURE_SPEECH_KEY:
        raise SpeechError(
            "Falta AZURE_SPEECH_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Azure.",
            status=500,
        )

    if client is None:
        client = AzureSpeechClient(
            settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION, settings.SPEECH_LANGUAGE
        )

    try:
        state = client.recognize(wav_path, "")
    except AzureSpeechError as error:
        raise SpeechError(f"Azure canceló la petición: {error}", status=502) from error

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


def assess_scripted(
    wav_path: str, reference_text: str, client: AzureSpeechClient | None = None
) -> dict:
    """Evalúa la pronunciación de un WAV CONTRA un texto de referencia (modo scripted).

    Es lo que usa la práctica de lectura. A diferencia del modo libre, acá sí hay
    `completeness` y miscue (omisiones/inserciones). `client` permite inyectar un doble.
    """
    if not settings.AZURE_SPEECH_KEY:
        raise SpeechError(
            "Falta AZURE_SPEECH_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Azure.",
            status=500,
        )

    # Azure espera la referencia en minúscula y sin puntuación; es además la forma en que
    # comparamos para detectar omisiones e inserciones.
    reference_words = [w.strip(string.punctuation) for w in reference_text.lower().split()]
    reference_words = [w for w in reference_words if w.strip()]
    if not reference_words:
        raise SpeechError("El texto de referencia no tiene palabras.", status=400)

    if client is None:
        client = AzureSpeechClient(
            settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION, settings.SPEECH_LANGUAGE
        )

    try:
        state = client.recognize(wav_path, " ".join(reference_words))
    except AzureSpeechError as error:
        raise SpeechError(f"Azure canceló la petición: {error}", status=502) from error

    if not state["words"]:
        raise SpeechError(
            "No se detectó voz en el audio. Revisa el micrófono e intenta de nuevo.",
            status=422,
        )

    return _aggregate_scripted(state, reference_words)


def _aggregate_scripted(state: dict, reference_words: list[str]) -> dict:
    """Combina los segmentos contra la referencia, con la lógica del sample oficial."""
    recognized = state["words"]

    # Azure no marca omisiones/inserciones en modo continuo: se derivan alineando lo
    # reconocido con el texto de referencia.
    diff = difflib.SequenceMatcher(
        None, reference_words, [w.word.lower() for w in recognized]
    )
    final_words = []
    for tag, i1, i2, j1, j2 in diff.get_opcodes():
        if tag in ("insert", "replace"):
            for word in recognized[j1:j2]:
                word._error_type = "Insertion"
                final_words.append(word)
        if tag in ("delete", "replace"):
            for word_text in reference_words[i1:i2]:
                final_words.append(AzureSpeechClient.make_omission_word(word_text))
        if tag == "equal":
            final_words.extend(recognized[j1:j2])

    # Accuracy por debajo de 60 sin otro error = mala pronunciación.
    for word in final_words:
        if word.error_type == "None" and word.accuracy_score < 60:
            word._error_type = "Mispronunciation"

    # Las inserciones no puntúan: el usuario no puede bajar su nota por decir de más lo que
    # el texto no pedía, solo se le marca.
    scored = [w for w in final_words if w.error_type != "Insertion"]
    accuracy = sum(w.accuracy_score for w in scored) / len(scored)

    prosody = (
        sum(state["prosody_scores"]) / len(state["prosody_scores"])
        if state["prosody_scores"]
        else None
    )

    span = state["end_offset"] - state["start_offset"]
    fluency = sum(state["durations"]) / span * 100 if span > 0 else 0.0

    correct = [w for w in final_words if w.error_type == "None"]
    completeness = min(100.0, len(correct) / len(scored) * 100) if scored else 0.0

    # Fórmula oficial: el peor score pesa más. Con prosodia son cuatro dimensiones.
    if prosody is not None:
        ordered = sorted([accuracy, prosody, completeness, fluency])
        pronunciation = ordered[0] * 0.4 + sum(ordered[1:]) * 0.2
    else:
        ordered = sorted([accuracy, fluency, completeness])
        pronunciation = ordered[0] * 0.6 + ordered[1] * 0.2 + ordered[2] * 0.2

    return {
        "recognized_text": " ".join(state["texts"]),
        "scores": {
            "pronunciation": round(pronunciation, 1),
            "accuracy": round(accuracy, 1),
            "fluency": round(fluency, 1),
            "completeness": round(completeness, 1),
            "prosody": round(prosody, 1) if prosody is not None else None,
        },
        "words": [AzureSpeechClient.word_to_dict(w) for w in final_words],
        # No estaba en el legacy: acá hace falta para cobrar el uso de Azure al presupuesto.
        "audio_seconds": round(max(0, span) / _TICKS_PER_SECOND, 3),
    }
