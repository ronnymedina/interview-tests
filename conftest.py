"""Configuracion compartida de los tests: cada test corre contra una BD temporal."""

import pytest

import config
import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Apunta la BD a un archivo temporal y crea el esquema limpio."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_file))
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
