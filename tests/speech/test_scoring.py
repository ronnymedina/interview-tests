"""Tests de la cola de scoring por conversación con una función de evaluación falsa."""

from app.speech.scoring import TurnScoring


def fake_result(pron, acc, fluency, prosody, words, seconds):
    return {
        "recognized_text": "x",
        "scores": {
            "pronunciation": pron,
            "accuracy": acc,
            "fluency": fluency,
            "completeness": None,
            "prosody": prosody,
        },
        "words": words,
        "audio_seconds": seconds,
    }


def test_enqueue_and_collect_returns_all_non_none_results():
    results = iter([
        fake_result(80, 80, 80, 70, [{"word": "a"}], 2.0),
        None,  # un turno sin voz se descarta
        fake_result(90, 90, 90, 90, [{"word": "b"}], 3.0),
    ])
    scoring = TurnScoring(assess_fn=lambda audio: next(results))

    scoring.enqueue("c1", b"111")
    scoring.enqueue("c1", b"222")
    scoring.enqueue("c1", b"333")
    collected = scoring.collect("c1")

    assert len(collected) == 2  # el None se descartó
    # collect vacía la conversación: un segundo collect no trae nada.
    assert scoring.collect("c1") == []


def test_aggregate_averages_scores_and_concatenates_words_and_seconds():
    scoring = TurnScoring(assess_fn=lambda audio: None)
    results = [
        fake_result(80, 80, 80, 70, [{"word": "a"}], 2.0),
        fake_result(90, 90, 90, 90, [{"word": "b"}], 3.0),
    ]
    agg = scoring.aggregate(results)

    assert agg["scores"]["pronunciation"] == 85.0
    assert agg["scores"]["prosody"] == 80.0
    assert [w["word"] for w in agg["words"]] == ["a", "b"]
    assert agg["audio_seconds"] == 5.0


def test_aggregate_ignores_none_prosody_in_average():
    scoring = TurnScoring(assess_fn=lambda audio: None)
    results = [
        fake_result(80, 80, 80, None, [], 1.0),
        fake_result(90, 90, 90, 60, [], 1.0),
    ]
    agg = scoring.aggregate(results)
    assert agg["scores"]["prosody"] == 60.0  # solo el turno con prosody cuenta


def test_aggregate_empty_results_gives_none_scores_and_zero_seconds():
    scoring = TurnScoring(assess_fn=lambda audio: None)
    agg = scoring.aggregate([])
    assert agg["scores"]["pronunciation"] is None
    assert agg["words"] == []
    assert agg["audio_seconds"] == 0.0
