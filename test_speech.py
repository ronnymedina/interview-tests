"""Caracteriza la logica de negocio de speech.py con un cliente Azure falso (sin red).

Verifica que la deteccion de omisiones/inserciones/mala pronunciacion y los scores se
mantienen tras separar la conexion a Azure en azure_speech.AzureSpeechClient.
"""

import azure.cognitiveservices.speech as speechsdk
import pytest

import config
import speech
from azure_speech import AzureSpeechError


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


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """assess() exige una key; en los tests basta una cualquiera."""
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "test-key")


def test_normalized_reference_is_passed_to_client():
    client = FakeClient(make_state([rec_word("hello", 95.0)], ["hello"]))
    speech.assess("a.wav", "Hello!", client=client)
    # El wrapper recibe el texto normalizado: minusculas y sin puntuacion.
    assert client.called_with == ("a.wav", "hello")


def test_mispronunciation_when_accuracy_below_60():
    state = make_state([rec_word("hello", 95.0), rec_word("world", 50.0)], ["hello world"])
    result = speech.assess("a.wav", "hello world", client=FakeClient(state))
    assert result["words"][0]["error_type"] == "None"
    assert result["words"][1]["error_type"] == "Mispronunciation"


def test_omission_detected_for_unspoken_word():
    state = make_state([rec_word("hello", 100.0)], ["hello"])
    result = speech.assess("a.wav", "hello world", client=FakeClient(state))
    omitted = [w for w in result["words"] if w["error_type"] == "Omission"]
    assert [w["word"] for w in omitted] == ["world"]
    # La omision entra al promedio de accuracy con 0, como en el sample oficial.
    assert result["scores"]["accuracy"] == 50.0


def test_insertion_detected_for_extra_word():
    state = make_state([rec_word("hello", 95.0), rec_word("there", 90.0)], ["hello there"])
    result = speech.assess("a.wav", "hello", client=FakeClient(state))
    inserted = [w for w in result["words"] if w["error_type"] == "Insertion"]
    assert [w["word"] for w in inserted] == ["there"]


def test_recognized_text_joins_segments():
    state = make_state([rec_word("hello", 95.0)], ["hello", "world"])
    result = speech.assess("a.wav", "hello", client=FakeClient(state))
    assert result["recognized_text"] == "hello world"


def test_missing_key_raises_500(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    with pytest.raises(speech.SpeechError) as error:
        speech.assess("a.wav", "hello", client=FakeClient(make_state([], [])))
    assert error.value.status == 500


def test_empty_reference_raises_400():
    with pytest.raises(speech.SpeechError) as error:
        speech.assess("a.wav", "!!!", client=FakeClient(make_state([], [])))
    assert error.value.status == 400


def test_no_speech_raises_422():
    with pytest.raises(speech.SpeechError) as error:
        speech.assess("a.wav", "hello", client=FakeClient(make_state([], [])))
    assert error.value.status == 422


def test_azure_cancel_translated_to_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(speech.SpeechError) as error:
        speech.assess("a.wav", "hello", client=client)
    assert error.value.status == 502
    assert "boom" in str(error.value)


def test_unscripted_passes_empty_reference():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    client = FakeClient(state)
    speech.assess_unscripted("a.wav", client=client)
    # Sin texto de referencia: se pasa cadena vacia al wrapper.
    assert client.called_with == ("a.wav", "")


def test_unscripted_scores_have_no_completeness():
    state = make_state([rec_word("hello", 90.0), rec_word("world", 80.0)],
                       ["hello world"], durations=[500000, 400000], end=1_000_000)
    result = speech.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["completeness"] is None
    assert result["scores"]["accuracy"] == 85.0
    assert result["recognized_text"] == "hello world"


def test_unscripted_mispronunciation_below_60():
    state = make_state([rec_word("hello", 40.0)], ["hello"], durations=[500000], end=600000)
    result = speech.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["words"][0]["error_type"] == "Mispronunciation"


def test_unscripted_with_prosody_averages_and_scores():
    # Con prosody, el overall usa la rama de 3 dimensiones (accuracy, fluency, prosody).
    state = make_state(
        [rec_word("hello", 90.0), rec_word("world", 80.0)],
        ["hello world"],
        durations=[500000, 400000],
        end=1_000_000,
        prosody=[70.0, 90.0],
    )
    result = speech.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["prosody"] == 80.0
    assert result["scores"]["pronunciation"] is not None


def test_unscripted_no_speech_raises_422():
    with pytest.raises(speech.SpeechError) as error:
        speech.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 422


def test_unscripted_missing_key_raises_500(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    with pytest.raises(speech.SpeechError) as error:
        speech.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 500


def test_unscripted_cancel_translated_to_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(speech.SpeechError) as error:
        speech.assess_unscripted("a.wav", client=client)
    assert error.value.status == 502
