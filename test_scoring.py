"""Tests del store de scoring en segundo plano (sin red: se mockea Azure)."""

import scoring
import speech


def _result(pronunciation, words):
    return {
        "recognized_text": "hello",
        "scores": {
            "pronunciation": pronunciation,
            "accuracy": pronunciation,
            "fluency": pronunciation,
            "completeness": None,
            "prosody": pronunciation,
        },
        "words": words,
    }


def test_enqueue_and_collect_returns_results(monkeypatch):
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: _result(80.0, []))
    scoring.enqueue("c1", b"audio-a")
    scoring.enqueue("c1", b"audio-b")
    results = scoring.collect("c1")
    assert len(results) == 2
    # collect vacia la conversacion: una segunda llamada no repite.
    assert scoring.collect("c1") == []


def test_failed_assessment_is_dropped(monkeypatch):
    def boom(wav_path):
        raise speech.SpeechError("no voz", status=422)

    monkeypatch.setattr(speech, "assess_unscripted", boom)
    scoring.enqueue("c2", b"audio")
    assert scoring.collect("c2") == []


def test_collect_unknown_conversation_is_empty():
    assert scoring.collect("nope") == []


def test_aggregate_averages_scores_and_concatenates_words():
    words_a = [{"word": "hello", "error_type": "None", "accuracy": 90.0, "phonemes": []}]
    words_b = [{"word": "world", "error_type": "None", "accuracy": 70.0, "phonemes": []}]
    scores, words = scoring.aggregate([_result(80.0, words_a), _result(90.0, words_b)])
    assert scores["pronunciation"] == 85.0
    assert [w["word"] for w in words] == ["hello", "world"]


def test_aggregate_ignores_none_scores():
    a = _result(80.0, [])
    a["scores"]["prosody"] = None
    b = _result(90.0, [])
    scores, _ = scoring.aggregate([a, b])
    assert scores["prosody"] == 90.0  # el None se ignora en el promedio
