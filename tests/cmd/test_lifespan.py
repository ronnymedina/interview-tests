"""Tests del lifespan: que el arranque aplique las migraciones y que se caiga si fallan.

Los otros tests del servidor usan TestClient sin `with`, asi que no disparan el lifespan.
Estos si, y por eso hay que neutralizar la tarea de ingesta: sin el parche, un Postgres
corriendo con el catalogo vacio haria que el test salga a scrapear la fuente real.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.cmd import server


@pytest.fixture(autouse=True)
def _sin_ingesta(monkeypatch):
    async def no_hace_nada(source, store):
        await asyncio.sleep(3600)

    monkeypatch.setattr(server, "ingest_loop", no_hace_nada)


def test_el_arranque_migra(monkeypatch):
    """El lifespan aplica las migraciones antes de atender la primera request."""
    llamadas = []
    monkeypatch.setattr(server, "apply_migrations", lambda: llamadas.append(True))

    with TestClient(server.app):
        pass

    assert llamadas == [True]


def test_una_migracion_fallida_tira_el_arranque(monkeypatch):
    """Cambio deliberado respecto del init_schema() anterior, que logueaba y seguia: eso
    dejaba la app arriba respondiendo 500 en todo lo que tocaba Postgres."""

    def explota():
        raise RuntimeError("migracion rota")

    monkeypatch.setattr(server, "apply_migrations", explota)

    with pytest.raises(RuntimeError, match="migracion rota"):
        with TestClient(server.app):
            pass
