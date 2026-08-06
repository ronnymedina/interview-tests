"""Configuracion compartida de los tests: cada test corre contra una BD temporal."""

import pytest

from config import settings
import db


@pytest.fixture(autouse=True)
def _clear_scoring():
    import scoring

    scoring._pending.clear()
    yield
    scoring._pending.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Limpia el contador del rate limiter entre tests para que no se acumulen los hits de
    la IP compartida del TestClient (evita 429 espurios). Solo actúa si el server ya se
    importó; no lo fuerza para no arrastrar sus dependencias a los tests que no lo usan."""
    import sys

    server = sys.modules.get("app.cmd.server")
    if server is not None:
        server._rate_limiter._counters.clear()
        server._rate_limiter._hits = 0
    yield


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Apunta la BD a un archivo temporal y crea el esquema limpio."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(settings, "DB_PATH", str(db_file))
    db.init_db()
    return str(db_file)


@pytest.fixture
def client(temp_db):
    """Cliente HTTP de la app contra la BD temporal."""
    from fastapi.testclient import TestClient

    import main

    return TestClient(main.app)


def make_result(words=None, pronunciation=90.0):
    """Un result normalizado minimo como el que devuelve speech.assess()."""
    if words is None:
        words = [
            {"word": "hello", "error_type": "None", "accuracy": 95.0, "phonemes": []},
            {"word": "world", "error_type": "Mispronunciation", "accuracy": 50.0, "phonemes": []},
        ]
    return {
        "recognized_text": "hello world",
        "scores": {
            "pronunciation": pronunciation,
            "accuracy": 88.0,
            "fluency": 80.0,
            "completeness": 100.0,
            "prosody": 70.0,
        },
        "words": words,
    }


def make_unscripted_result(recognized="hello world", pronunciation=85.0):
    """Un result de speech.assess_unscripted() minimo (sin completeness)."""
    return {
        "recognized_text": recognized,
        "scores": {
            "pronunciation": pronunciation,
            "accuracy": 88.0,
            "fluency": 80.0,
            "completeness": None,
            "prosody": 70.0,
        },
        "words": [
            {"word": "hello", "error_type": "None", "accuracy": 95.0, "phonemes": []},
        ],
    }
