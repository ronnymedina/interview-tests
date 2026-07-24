"""Logica de evaluacion de pronunciacion.

Normaliza el texto de referencia, pide a Azure la evaluacion a traves de
`AzureSpeechClient` (el wrapper que habla con el API) y transforma el resultado crudo en
el dict normalizado que la pagina pinta. Este archivo NO habla directamente con el SDK de
Azure: toda la conexion vive en `azure_speech.py`.

Azure no marca omisiones/inserciones en modo continuo, asi que las derivamos comparando lo
reconocido contra el texto de referencia (con difflib), tal como el sample oficial.
"""

import difflib
import string

import config
from azure_speech import AzureSpeechClient, AzureSpeechError


class SpeechError(Exception):
    """Error pensado para mostrarse tal cual al usuario. `status` es el codigo HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def assess(wav_path: str, reference_text: str, client: AzureSpeechClient | None = None) -> dict:
    """Evalua la pronunciacion de un WAV contra un texto de referencia.

    `client` permite inyectar un doble en los tests; en produccion se construye desde la
    configuracion.
    """
    if not config.AZURE_SPEECH_KEY:
        raise SpeechError(
            "Falta AZURE_SPEECH_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Azure.",
            status=500,
        )

    # Normalizamos el texto de referencia a palabras en minuscula sin puntuacion, que es
    # lo que Azure espera y lo que usamos para detectar omisiones/inserciones.
    reference_words = [w.strip(string.punctuation) for w in reference_text.lower().split()]
    reference_words = [w for w in reference_words if w.strip()]
    if not reference_words:
        raise SpeechError("El texto de referencia no tiene palabras.", status=400)

    if client is None:
        client = AzureSpeechClient(
            config.AZURE_SPEECH_KEY, config.AZURE_SPEECH_REGION, config.SPEECH_LANGUAGE
        )

    try:
        state = client.recognize(wav_path, " ".join(reference_words))
    except AzureSpeechError as error:
        raise SpeechError(f"Azure cancelo la peticion: {error}", status=502)

    if not state["words"]:
        raise SpeechError(
            "No se detecto voz en el audio. Revisa el microfono e intenta de nuevo.",
            status=422,
        )

    return _aggregate(state, reference_words)


def _aggregate(state: dict, reference_words: list[str]) -> dict:
    """Combina los segmentos en un solo resultado con la misma logica del sample oficial."""
    recognized = state["words"]

    # Azure no marca omisiones/inserciones en modo continuo: las derivamos comparando
    # las palabras reconocidas contra el texto de referencia.
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

    # Accuracy por debajo de 60 sin otro error = mala pronunciacion.
    for word in final_words:
        if word.error_type == "None" and word.accuracy_score < 60:
            word._error_type = "Mispronunciation"

    # --- scores globales ---
    scored = [w for w in final_words if w.error_type != "Insertion"]
    accuracy = sum(w.accuracy_score for w in scored) / len(scored)

    prosody = (
        sum(state["prosody_scores"]) / len(state["prosody_scores"])
        if state["prosody_scores"]
        else None
    )

    span = state["end_offset"] - state["start_offset"]
    fluency = sum(state["durations"]) / span * 100 if span > 0 else 0.0

    handled = [w for w in final_words if w.error_type != "Insertion"]
    correct = [w for w in final_words if w.error_type == "None"]
    completeness = min(100.0, len(correct) / len(handled) * 100) if handled else 0.0

    # Formula oficial: el peor score pesa mas. Con prosodia son cuatro dimensiones.
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
    }
