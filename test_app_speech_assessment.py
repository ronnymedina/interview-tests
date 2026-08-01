"""Caracteriza assess_unscripted del módulo app/speech con un cliente Azure falso (sin red)."""

import azure.cognitiveservices.speech as speechsdk
import pytest

import config
from app.speech import assessment
from app.speech.azure_client import AzureSpeechError


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
    """assess_unscripted exige una key; en los tests basta una cualquiera."""
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "test-key")


def test_unscripted_passes_empty_reference():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    client = FakeClient(state)
    assessment.assess_unscripted("a.wav", client=client)
    assert client.called_with == ("a.wav", "")


def test_unscripted_scores_have_no_completeness():
    state = make_state([rec_word("hello", 90.0), rec_word("world", 80.0)],
                       ["hello world"], durations=[500000, 400000], end=1_000_000)
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["completeness"] is None
    assert result["scores"]["accuracy"] == 85.0
    assert result["recognized_text"] == "hello world"


def test_unscripted_reports_audio_seconds():
    # start=1000, end=10_000_000 ticks -> (10_000_000 - 1000)/10_000_000 ≈ 0.9999 s.
    state = make_state([rec_word("hello", 90.0)], ["hello"], durations=[500000],
                       start=1000, end=10_000_000)
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["audio_seconds"] == pytest.approx(0.9999, abs=1e-3)


def test_unscripted_mispronunciation_below_60():
    state = make_state([rec_word("hello", 40.0)], ["hello"], durations=[500000], end=600000)
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["words"][0]["error_type"] == "Mispronunciation"


def test_unscripted_with_prosody_averages_and_scores():
    state = make_state(
        [rec_word("hello", 90.0), rec_word("world", 80.0)],
        ["hello world"],
        durations=[500000, 400000],
        end=1_000_000,
        prosody=[70.0, 90.0],
    )
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["prosody"] == 80.0
    assert result["scores"]["pronunciation"] is not None


def test_unscripted_no_speech_raises_422():
    with pytest.raises(assessment.SpeechError) as error:
        assessment.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 422


def test_unscripted_missing_key_raises_500(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    with pytest.raises(assessment.SpeechError) as error:
        assessment.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 500


def test_unscripted_cancel_translated_to_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(assessment.SpeechError) as error:
        assessment.assess_unscripted("a.wav", client=client)
    assert error.value.status == 502
    assert "boom" in str(error.value)
