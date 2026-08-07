"""Adaptador del SDK de Azure Speech (Pronunciation Assessment) para el módulo app/.

Único punto que habla con el SDK: configura, corre el reconocimiento continuo y devuelve
datos crudos. No hace lógica de negocio (esa vive en assessment.py). Migrado del legacy
azure_speech.py; se conserva solo lo que usa el modo unscripted del piloto.
"""

import json
import threading
from typing import Any

import azure.cognitiveservices.speech as speechsdk

# Azure entrega tiempos en unidades de 100 ns. Cada palabra suma este colchón de duración,
# igual que el sample oficial, para el cálculo de fluidez de assessment.py.
_TICK_PADDING = 100000


class AzureSpeechError(Exception):
    """Azure canceló la petición. El mensaje trae el motivo que reportó el servicio."""


class AzureSpeechClient:
    """Cliente delgado sobre el SDK de Azure para evaluar pronunciación.

    Recibe las credenciales ya tipadas (no lee variables de entorno) y expone `recognize()`,
    que corre la evaluación sobre un WAV y devuelve datos crudos.
    """

    def __init__(self, key: str, region: str, language: str):
        self._key = key
        self._region = region
        self._language = language

    def recognize(self, wav_path: str, reference_text: str) -> dict:
        """Corre el pronunciation assessment sobre un WAV y devuelve los datos crudos.

        Devuelve un dict con: `words`, `prosody_scores`, `durations`, `texts`, `start_offset`
        y `end_offset`. Lanza `AzureSpeechError` si Azure cancela.
        """
        speech_config = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        speech_config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "1500"
        )
        audio_config = speechsdk.audio.AudioConfig(filename=wav_path)

        pron_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=bool(reference_text),
        )
        pron_config.enable_prosody_assessment()
        pron_config.phoneme_alphabet = "IPA"

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            language=self._language,
            audio_config=audio_config,
        )
        pron_config.apply_to(recognizer)

        return self._run_continuous(recognizer)

    @staticmethod
    def _run_continuous(recognizer: "speechsdk.SpeechRecognizer") -> dict:
        """Corre el reconocimiento continuo y junta los resultados de todos los segmentos."""
        done = threading.Event()
        state: dict[str, Any] = {
            "words": [],
            "prosody_scores": [],
            "durations": [],
            "texts": [],
            "start_offset": 0,
            "end_offset": 0,
            "cancel_error": None,
        }

        def on_recognized(evt: "speechsdk.SpeechRecognitionEventArgs") -> None:
            result = speechsdk.PronunciationAssessmentResult(evt.result)
            state["words"].extend(result.words)
            if result.prosody_score is not None:
                state["prosody_scores"].append(result.prosody_score)
            if evt.result.text:
                state["texts"].append(evt.result.text)

            raw = evt.result.properties.get(
                speechsdk.PropertyId.SpeechServiceResponse_JsonResult
            )
            words_json = json.loads(raw)["NBest"][0]["Words"]
            state["durations"].extend(
                int(w["Duration"]) + _TICK_PADDING
                for w in words_json
                if w["PronunciationAssessment"]["ErrorType"] == "None"
            )
            if state["start_offset"] == 0:
                state["start_offset"] = words_json[0]["Offset"]
            last = words_json[-1]
            state["end_offset"] = last["Offset"] + last["Duration"] + _TICK_PADDING

        def on_canceled(evt: "speechsdk.SpeechRecognitionCanceledEventArgs") -> None:
            details = evt.cancellation_details
            if details.reason == speechsdk.CancellationReason.Error:
                state["cancel_error"] = details.error_details or "sin detalle"
            done.set()

        recognizer.recognized.connect(on_recognized)
        recognizer.session_stopped.connect(lambda evt: done.set())
        recognizer.canceled.connect(on_canceled)

        recognizer.start_continuous_recognition()
        done.wait()
        recognizer.stop_continuous_recognition()

        if state["cancel_error"]:
            raise AzureSpeechError(state["cancel_error"])
        del state["cancel_error"]
        return state

    @staticmethod
    def make_omission_word(text: str) -> "speechsdk.PronunciationAssessmentWordResult":
        """Crea un objeto-palabra sintético marcado como omisión (no se pronunció).

        Azure no reporta las palabras que el usuario se saltó: solo devuelve lo que oyó. Las
        omisiones se derivan comparando contra el texto de referencia, y hacen falta como
        objetos del SDK para que el resto del agregado las trate igual que a las reales.
        """
        return speechsdk.PronunciationAssessmentWordResult(
            {"Word": text, "PronunciationAssessment": {"ErrorType": "Omission"}}
        )

    @staticmethod
    def word_to_dict(word: "speechsdk.PronunciationAssessmentWordResult") -> dict:
        """Convierte una palabra del SDK al dict plano que consume la página."""
        try:
            phonemes = [
                {"phoneme": ph.phoneme, "accuracy": ph.accuracy_score}
                for ph in (word.phonemes or [])
            ]
        except AttributeError:
            phonemes = []
        return {
            "word": word.word,
            "accuracy": word.accuracy_score,
            "error_type": word.error_type,
            "phonemes": phonemes,
        }
