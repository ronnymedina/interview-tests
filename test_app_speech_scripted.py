"""Caracteriza assess_scripted con un cliente Azure falso (sin red).

Reusa los helpers de test_app_speech_assessment.py: mismo formato de `state` crudo.
"""

import pytest

from config import settings
from app.speech import assessment
from app.speech.azure_client import AzureSpeechError
from test_app_speech_assessment import FakeClient, make_state, rec_word


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_SPEECH_KEY", "test-key")


def test_manda_el_texto_de_referencia_normalizado():
    """Azure espera palabras en minúscula sin puntuación."""
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    client = FakeClient(state)
    assessment.assess_scripted("a.wav", "Hello, world!", client=client)
    assert client.called_with == ("a.wav", "hello world")


def test_referencia_sin_palabras_es_error_400():
    with pytest.raises(assessment.SpeechError) as exc:
        assessment.assess_scripted("a.wav", "  ...  ", client=FakeClient(make_state([], [])))
    assert exc.value.status == 400


def test_palabra_no_dicha_se_marca_como_omision():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    errors = {w["word"]: w["error_type"] for w in result["words"]}
    assert errors["world"] == "Omission"


def test_palabra_de_mas_se_marca_como_insercion():
    state = make_state(
        [rec_word("hello", 95.0), rec_word("there", 90.0), rec_word("world", 92.0)],
        ["hello there world"], durations=[300000, 300000, 300000], end=1_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    errors = {w["word"]: w["error_type"] for w in result["words"]}
    assert errors["there"] == "Insertion"


def test_lectura_perfecta_da_completeness_100():
    state = make_state(
        [rec_word("hello", 95.0), rec_word("world", 92.0)],
        ["hello world"], durations=[400000, 400000], end=1_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    assert result["scores"]["completeness"] == 100.0


def test_completeness_baja_con_omisiones():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    assert result["scores"]["completeness"] == 50.0


def test_accuracy_baja_sin_otro_error_es_mispronunciation():
    state = make_state(
        [rec_word("hello", 95.0), rec_word("world", 40.0)],
        ["hello world"], durations=[400000, 400000], end=1_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    errors = {w["word"]: w["error_type"] for w in result["words"]}
    assert errors["world"] == "Mispronunciation"


def test_devuelve_audio_seconds_para_el_costo():
    """El legacy no lo tenía; acá hace falta para cobrar el uso de Azure."""
    state = make_state(
        [rec_word("hello", 95.0)], ["hello"], durations=[500000], start=0, end=10_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello", client=FakeClient(state))
    assert result["audio_seconds"] == 1.0


def test_azure_cancelado_es_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(assessment.SpeechError) as exc:
        assessment.assess_scripted("a.wav", "hello", client=client)
    assert exc.value.status == 502


def test_sin_voz_detectada_es_422():
    client = FakeClient(make_state([], []))
    with pytest.raises(assessment.SpeechError) as exc:
        assessment.assess_scripted("a.wav", "hello", client=client)
    assert exc.value.status == 422
