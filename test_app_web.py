"""Smoke tests del frontend servido por plantillas.

No validan el diseño (eso se mira en el navegador); validan el contrato de que la página
se renderiza, hereda del base y los estáticos se sirven desde /static. Sin esto, un error
de ruta en las plantillas solo aparecería en producción."""

from fastapi.testclient import TestClient

from app.cmd import server


def _client() -> TestClient:
    return TestClient(server.app)


def test_index_renders():
    response = _client().get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_index_extends_base():
    """El banner vive en base.html: si aparece en la página, la herencia funcionó."""
    body = _client().get("/").text
    assert 'id="banner"' in body
    assert 'id="step-voice"' in body


def test_index_links_shared_stylesheet():
    body = _client().get("/").text
    assert "/static/app.css" in body


def test_stylesheet_is_served():
    response = _client().get("/static/app.css")
    assert response.status_code == 200
    assert "--cream" in response.text


def test_shared_script_is_served():
    response = _client().get("/static/shared.js")
    assert response.status_code == 200
    assert "createRecorder" in response.text
    assert "encodeWav" in response.text


def test_index_loads_shared_script():
    assert "/static/shared.js" in _client().get("/").text
