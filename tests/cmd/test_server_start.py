"""Tests del endpoint /conversation/start: límites, registro de uso e identidad de usuario.

Se inyectan dobles de los servicios vía app.dependency_overrides (sin red, sin Postgres, sin
LLM). Con dobles no hay usage_metadata real, así que los tokens registrados son 0; lo que se
verifica es el CABLEADO: que se consulte la cuota, se registre el inicio y el usage_event.
"""

import pytest
from fastapi.testclient import TestClient

from app.cmd import server
from app.limits.model import Decision, DecisionKind


class FakeConversationService:
    def __init__(self):
        self.started_with = None

    def start(self, user_context, max_questions):
        self.started_with = (user_context, max_questions)
        return "conv-123", "What's your name?", 1, 5


class FakeLimits:
    def __init__(self, decision=Decision(DecisionKind.ALLOW), raises=False):
        self._decision = decision
        self._raises = raises
        self.starts = []
        self.gemini = []

    def check_can_start(self, user_id):
        if self._raises:
            raise RuntimeError("db down")
        return self._decision

    def record_conversation_start(self, user_id, conversation_id):
        self.starts.append((user_id, conversation_id))

    def record_gemini_usage(self, user_id, conversation_id, kind, input_tokens, output_tokens):
        self.gemini.append((user_id, conversation_id, kind, input_tokens, output_tokens))
        return 0.0


@pytest.fixture
def client_with(monkeypatch):
    """Devuelve una fábrica que arma el TestClient con dobles inyectados."""

    def _make(conversation=None, limits=None):
        conversation = conversation or FakeConversationService()
        limits = limits or FakeLimits()
        server.app.dependency_overrides[server.get_conversation_service] = lambda: conversation
        server.app.dependency_overrides[server.get_limits_service] = lambda: limits
        return TestClient(server.app), conversation, limits

    yield _make
    server.app.dependency_overrides.clear()


def test_start_requires_user_id(client_with):
    client, _, _ = client_with()
    resp = client.post("/conversation/start", json={"user_context": "hola"})
    assert resp.status_code == 400


def test_start_allows_and_records(client_with):
    client, _, limits = client_with()
    resp = client.post(
        "/conversation/start",
        json={"user_context": "practicar para entrevista"},
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "conversation_id": "conv-123",
        "question": "What's your name?",
        "question_number": 1,
        "total_questions": 5,
    }
    # cableado: se registró el inicio y un usage_event de Gemini con kind 'synthesis'.
    assert limits.starts == [("u1", "conv-123")]
    assert len(limits.gemini) == 1
    assert limits.gemini[0][2] == "synthesis"


def test_start_blocked_by_quota_returns_429(client_with):
    limits = FakeLimits(decision=Decision(DecisionKind.QUOTA))
    client, _, _ = client_with(limits=limits)
    resp = client.post(
        "/conversation/start", json={"user_context": "x"}, headers={"X-User-Id": "u1"}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == {"reason": "quota"}
    assert limits.starts == []  # no arrancó


def test_start_blocked_by_pause_returns_429(client_with):
    limits = FakeLimits(decision=Decision(DecisionKind.PAUSED_TOTAL))
    client, _, _ = client_with(limits=limits)
    resp = client.post(
        "/conversation/start", json={"user_context": "x"}, headers={"X-User-Id": "u1"}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == {"reason": "paused"}


def test_start_db_down_cuts_conservative_as_paused(client_with):
    limits = FakeLimits(raises=True)
    client, _, _ = client_with(limits=limits)
    resp = client.post(
        "/conversation/start", json={"user_context": "x"}, headers={"X-User-Id": "u1"}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == {"reason": "paused"}
