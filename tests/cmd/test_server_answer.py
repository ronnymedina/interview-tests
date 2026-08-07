"""Tests del endpoint /conversation/answer (multipart): scoring encolado, uso y merge final.

Dobles inyectados vía dependency_overrides. El audio es un WAV de bytes arbitrarios (el doble de
speech no lo procesa). Se verifica el cableado: encolar el audio, registrar uso, y en el turno
final combinar el feedback de Gemini con la evaluación de pronunciación.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.cmd import server


class FakeConversationService:
    def __init__(self, result):
        self._result = result
        self.answered_with = None

    def answer(self, conversation_id, recognized_text):
        self.answered_with = (conversation_id, recognized_text)
        return self._result


class FakeLimits:
    def __init__(self):
        self.gemini = []
        self.azure = []

    def record_gemini_usage(self, user_id, conversation_id, kind, input_tokens, output_tokens):
        self.gemini.append((user_id, conversation_id, kind, input_tokens, output_tokens))
        return 0.0

    def record_azure_usage(self, user_id, conversation_id, audio_seconds):
        self.azure.append((user_id, conversation_id, audio_seconds))
        return 0.0


class FakeSpeech:
    def __init__(self, pronunciation=None):
        self._pronunciation = pronunciation or {
            "scores": {"pronunciation": 80.0}, "words": [], "audio_seconds": 4.0
        }
        self.enqueued = []

    def score_answer(self, conversation_id, audio_bytes):
        self.enqueued.append((conversation_id, audio_bytes))

    def final_pronunciation(self, conversation_id):
        return self._pronunciation


def _post_answer(client, *, conversation_id="c1", transcript="hello world", audio=b"RIFFfake"):
    return client.post(
        "/conversation/answer",
        data={"conversation_id": conversation_id, "transcript": transcript},
        files={"audio": ("answer.wav", io.BytesIO(audio), "audio/wav")},
        headers={"X-User-Id": "u1"},
    )


@pytest.fixture
def client_with():
    def _make(result, speech=None, limits=None):
        conversation = FakeConversationService(result)
        limits = limits or FakeLimits()
        speech = speech  # None => sin Azure
        server.app.dependency_overrides[server.get_conversation_service] = lambda: conversation
        server.app.dependency_overrides[server.get_limits_service] = lambda: limits
        server.app.dependency_overrides[server.get_speech_service] = lambda: speech
        return TestClient(server.app), conversation, limits, speech

    yield _make
    server.app.dependency_overrides.clear()


def test_answer_requires_user_id(client_with):
    client, *_ = client_with({"question": "next?"}, speech=FakeSpeech())
    resp = client.post(
        "/conversation/answer",
        data={"conversation_id": "c1", "transcript": "hi"},
        files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")},
    )
    assert resp.status_code == 400


def test_answer_normal_turn_enqueues_audio_and_returns_question(client_with):
    speech = FakeSpeech()
    client, conversation, limits, _ = client_with({"question": "And then?"}, speech=speech)
    resp = _post_answer(client)
    assert resp.status_code == 200
    assert resp.json() == {"question": "And then?"}
    assert speech.enqueued == [("c1", b"RIFFfake")]        # audio encolado
    assert conversation.answered_with == ("c1", "hello world")  # transcript al grafo
    assert limits.gemini[0][2] == "question"               # usage_event kind 'question'
    assert limits.azure == []                              # sin Azure en turno normal


def test_answer_final_turn_merges_pronunciation(client_with):
    final = {"final": {"content_feedback": "bien", "practice_words": []}}
    pronunciation = {"scores": {"pronunciation": 90.0}, "words": [], "audio_seconds": 6.0}
    speech = FakeSpeech(pronunciation=pronunciation)
    client, _, limits, _ = client_with(final, speech=speech)
    resp = _post_answer(client, transcript="that is all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["final"]["pronunciation"] == pronunciation
    assert limits.gemini[0][2] == "feedback"              # usage_event Gemini kind 'feedback'
    assert limits.azure == [("u1", "c1", 6.0)]            # usage_event Azure por duración


def test_answer_final_turn_without_azure_sets_pronunciation_null(client_with):
    final = {"final": {"content_feedback": "bien", "practice_words": []}}
    client, _, limits, _ = client_with(final, speech=None)  # sin SpeechService
    resp = _post_answer(client, transcript="done")
    assert resp.status_code == 200
    assert resp.json()["final"]["pronunciation"] is None
    assert limits.azure == []


def test_answer_empty_transcript_returns_422(client_with):
    client, *_ = client_with({"question": "x"}, speech=FakeSpeech())
    resp = _post_answer(client, transcript="   ")
    assert resp.status_code == 422
