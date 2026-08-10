"""Configuracion compartida de los tests de app/cmd."""

import pytest

from app.cmd import server


@pytest.fixture(autouse=True)
def _sin_migraciones_reales(monkeypatch):
    """Neutraliza `apply_migrations` por default para todo test de este paquete.

    Cualquier test que use `with TestClient(app)` dispara el lifespan, que llama a
    `apply_migrations()` y por lo tanto abre una conexion real a Postgres. Sin este
    parche, un test nuevo que no sepa esto falla en CI con un psycopg.OperationalError
    opaco contra localhost:5432, en vez de con un mensaje que explique que falto mockear.

    Es autouse pero no definitivo: un test puede pisarlo con su propio
    `monkeypatch.setattr(server, "apply_migrations", ...)`, como hace
    `test_una_migracion_fallida_tira_el_arranque`, que necesita que falle de verdad.
    """
    monkeypatch.setattr(server, "apply_migrations", lambda: None)
