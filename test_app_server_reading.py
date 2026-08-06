"""Los endpoints de lectura con servicios falsos inyectados por dependency_overrides."""

import pytest
from fastapi.testclient import TestClient

from app.cmd.server import app, get_limits_service, get_reading_service
from app.limits.model import Decision, DecisionKind
from app.reading.service import ReadingError

HEADERS = {"X-User-Id": "u1"}

SAMPLE = {
    "reading_id": 7,
    "title": "Daily news",
    "level": 5,
    "source_url": "https://engoo.com/a",
    "excerpt": "One two three.",
    "word_count": 3,
}


class FakeReadingService:
    def __init__(self, random_result=None, assess_result=None, error=None):
        self._random = random_result or SAMPLE
        self._assess = assess_result or {"scores": {}, "words": [], "reference_text": "x"}
        self._error = error
        self.assessed = None

    async def random_excerpt(self):
        if self._error:
            raise self._error
        return self._random

    async def assess(self, reading_id, audio_bytes):
        if self._error:
            raise self._error
        self.assessed = (reading_id, audio_bytes)
        return self._assess


class FakeLimits:
    def __init__(self, decision=None):
        self._decision = decision or Decision(DecisionKind.ALLOW)
        self.reading_starts = []
        self.azure_usage = []

    def check_can_read(self, user_id):
        return self._decision

    def record_reading_start(self, user_id, reading_id):
        self.reading_starts.append((user_id, reading_id))

    def record_azure_usage(self, user_id, conversation_id, audio_seconds, kind="assessment"):
        self.azure_usage.append((user_id, conversation_id, audio_seconds, kind))
        return 0.01


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_random_devuelve_el_extracto(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.get("/reading/random", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == SAMPLE


def test_random_no_consume_cuota(client):
    """Pedir texto no cuesta dinero: la cuota se cobra al evaluar."""
    limits = FakeLimits()
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: limits

    client.get("/reading/random", headers=HEADERS)

    assert limits.reading_starts == []


def test_random_corta_con_429_si_el_presupuesto_esta_agotado(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits(
        Decision(DecisionKind.PAUSED_TOTAL)
    )

    res = client.get("/reading/random", headers=HEADERS)

    assert res.status_code == 429
    assert res.json()["detail"]["reason"] == "paused"


def test_random_con_catalogo_vacio_es_503(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("sin textos", status=503)
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.get("/reading/random", headers=HEADERS)

    assert res.status_code == 503


def test_random_exige_x_user_id(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    assert client.get("/reading/random").status_code == 400


def test_la_pagina_de_lectura_se_renderiza(client):
    res = client.get("/reading")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
