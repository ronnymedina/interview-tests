"""Dobles y constructores compartidos por los tests de app/speech.

Viven acá y no dentro de un test para que test_scripted.py no tenga que importar de
test_assessment.py: un test que importa de otro test acopla dos suites que deberían poder
moverse por separado.
"""

import azure.cognitiveservices.speech as speechsdk


def rec_word(word, accuracy, error="None"):
    """Un objeto-palabra del SDK como los que devuelve el reconocimiento real."""
    return speechsdk.PronunciationAssessmentWordResult(
        {"Word": word, "PronunciationAssessment": {"ErrorType": error, "AccuracyScore": accuracy}}
    )


def make_state(words, texts, *, durations=None, start=1000, end=1_000_000, prosody=None):
    return {
        "words": words,
        "prosody_scores": prosody or [],
        "durations": durations or [],
        "texts": texts,
        "start_offset": start,
        "end_offset": end,
    }


class FakeClient:
    """Doble de AzureSpeechClient: devuelve un state fijo o lanza un error."""

    def __init__(self, state=None, error=None):
        self._state = state
        self._error = error
        self.called_with = None

    def recognize(self, wav_path, reference_text):
        self.called_with = (wav_path, reference_text)
        if self._error:
            raise self._error
        return self._state
