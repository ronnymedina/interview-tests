"""Tests del endpoint POST /feedback: identidad, validación y persistencia (con repo doble)."""

import pytest
from fastapi.testclient import TestClient

from app.cmd import server


class FakeFeedbackRepo:
    """Doble de FeedbackRepository: captura lo guardado y devuelve un id fijo."""

    def __init__(self):
        self.saved = []

    def save(self, user_id, feedback):
        self.saved.append((user_id, feedback))
        return 42


@pytest.fixture
def client_with():
    def _make(repo=None):
        repo = repo or FakeFeedbackRepo()
        server.app.dependency_overrides[server.get_feedback_repository] = lambda: repo
        return TestClient(server.app), repo

    yield _make
    server.app.dependency_overrides.clear()


def test_feedback_requires_user_id(client_with):
    client, _ = client_with()
    resp = client.post("/feedback", json={"liked": True, "rating": 5})
    assert resp.status_code == 400


def test_feedback_saved_returns_201_with_id(client_with):
    client, repo = client_with()
    resp = client.post(
        "/feedback",
        json={"liked": True, "rating": 5, "comment": "genial", "wants_more": True,
              "suggestions": "más juegos"},
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"id": 42}
    assert len(repo.saved) == 1
    user_id, feedback = repo.saved[0]
    assert user_id == "u1"
    assert feedback.rating == 5
    assert feedback.suggestions == "más juegos"


def test_feedback_invalid_rating_returns_422(client_with):
    client, _ = client_with()
    resp = client.post("/feedback", json={"rating": 9}, headers={"X-User-Id": "u1"})
    assert resp.status_code == 422


def test_feedback_minimal_body_ok(client_with):
    # Todo opcional: un body vacío es válido (el usuario no llenó nada).
    client, repo = client_with()
    resp = client.post("/feedback", json={}, headers={"X-User-Id": "u1"})
    assert resp.status_code == 201
    assert repo.saved[0][1].comment == ""
