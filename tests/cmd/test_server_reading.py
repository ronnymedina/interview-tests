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
        self.asked_max_level = None

    async def random_excerpt(self, max_level=None):
        self.asked_max_level = max_level
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


# --- POST /reading/assess ---------------------------------------------------------------

ASSESS_RESULT = {
    "recognized_text": "one two three",
    "scores": {"pronunciation": 88.0, "completeness": 100.0},
    "words": [{"word": "one", "accuracy": 90.0, "error_type": "None", "phonemes": []}],
    "audio_seconds": 12.5,
    "reference_text": "One two three.",
}


def _post_assess(client, reading_id=7):
    return client.post(
        "/reading/assess",
        data={"reading_id": str(reading_id)},
        files={"audio": ("a.wav", b"fake wav bytes", "audio/wav")},
        headers=HEADERS,
    )


def test_assess_devuelve_los_scores(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        assess_result=ASSESS_RESULT
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = _post_assess(client)

    assert res.status_code == 200
    assert res.json()["scores"]["completeness"] == 100.0


def test_assess_cobra_la_cuota_y_el_costo(client):
    limits = FakeLimits()
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        assess_result=ASSESS_RESULT
    )
    app.dependency_overrides[get_limits_service] = lambda: limits

    _post_assess(client)

    assert limits.reading_starts == [("u1", 7)]
    assert limits.azure_usage == [("u1", "7", 12.5, "reading_assessment")]


def test_assess_corta_con_429_sin_cuota(client):
    limits = FakeLimits(Decision(DecisionKind.QUOTA))
    service = FakeReadingService(assess_result=ASSESS_RESULT)
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: limits

    res = _post_assess(client)

    assert res.status_code == 429
    assert res.json()["detail"]["reason"] == "quota"
    # No se llamó a Azure: los límites se comprueban ANTES de gastar.
    assert service.assessed is None


def test_assess_con_id_inexistente_es_404(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("no existe", status=404)
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    assert _post_assess(client, reading_id=999).status_code == 404


def test_assess_no_cobra_si_azure_falla(client):
    """Un 502 de Azure no debe gastarle una lectura al usuario."""
    limits = FakeLimits()
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("Azure canceló", status=502)
    )
    app.dependency_overrides[get_limits_service] = lambda: limits

    res = _post_assess(client)

    assert res.status_code == 502
    assert limits.reading_starts == []
    assert limits.azure_usage == []


def test_assess_ignora_un_reference_text_enviado_por_el_cliente(client):
    """El texto lo pone el servidor: si no, cualquiera evalúa 'hello' contra 'hello'."""
    service = FakeReadingService(assess_result=ASSESS_RESULT)
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.post(
        "/reading/assess",
        data={"reading_id": "7", "reference_text": "hello"},
        files={"audio": ("a.wav", b"fake wav bytes", "audio/wav")},
        headers=HEADERS,
    )

    assert res.status_code == 200
    # El servicio solo recibió el id y el audio; el texto extra se descartó.
    assert service.assessed == (7, b"fake wav bytes")


# --- filtro por nivel máximo ------------------------------------------------------------

def test_random_pasa_el_nivel_maximo_al_servicio(client):
    service = FakeReadingService()
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    client.get("/reading/random?max_level=5", headers=HEADERS)

    assert service.asked_max_level == 5


def test_random_sin_nivel_no_filtra(client):
    service = FakeReadingService()
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    client.get("/reading/random", headers=HEADERS)

    assert service.asked_max_level is None


def test_un_nivel_maximo_invalido_es_422(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    assert client.get("/reading/random?max_level=0", headers=HEADERS).status_code == 422
    assert client.get("/reading/random?max_level=99", headers=HEADERS).status_code == 422
    assert client.get("/reading/random?max_level=x", headers=HEADERS).status_code == 422


def test_sin_textos_del_nivel_pedido_es_503(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("No hay textos de nivel 4 o menos", status=503)
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.get("/reading/random?max_level=4", headers=HEADERS)

    assert res.status_code == 503
    assert "nivel 4" in res.json()["detail"]
