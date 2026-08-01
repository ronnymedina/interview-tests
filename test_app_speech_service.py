"""Tests del SpeechService: construcción desde config e integración cola+agregación."""

import config
from app.speech import SpeechService, build_speech_service


def fake_result(seconds, words):
    return {
        "recognized_text": "x",
        "scores": {
            "pronunciation": 80.0,
            "accuracy": 80.0,
            "fluency": 80.0,
            "completeness": None,
            "prosody": None,
        },
        "words": words,
        "audio_seconds": seconds,
    }


def test_build_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    assert build_speech_service() is None


def test_build_returns_service_with_key(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "test-key")
    service = build_speech_service()
    assert isinstance(service, SpeechService)


def test_score_answer_then_final_pronunciation_aggregates():
    # Inyectamos una función de evaluación falsa vía el constructor (sin red).
    results = iter([fake_result(2.0, [{"word": "a"}]), fake_result(3.0, [{"word": "b"}])])
    service = SpeechService(assess_fn=lambda audio: next(results))

    service.score_answer("c1", b"111")
    service.score_answer("c1", b"222")
    final = service.final_pronunciation("c1")

    assert final["audio_seconds"] == 5.0
    assert [w["word"] for w in final["words"]] == ["a", "b"]
    assert final["scores"]["pronunciation"] == 80.0
