"""Tests de la capa de datos: textos guardados e intentos ligados a un texto."""

from conftest import make_result

import db


def test_create_and_get_text(temp_db):
    text_id = db.create_text("Saludo", "Hello world.", 3)
    text = db.get_text(text_id)
    assert text["title"] == "Saludo"
    assert text["content"] == "Hello world."
    assert text["difficulty"] == 3


def test_create_text_without_difficulty(temp_db):
    text_id = db.create_text("Sin nivel", "Some text.", None)
    assert db.get_text(text_id)["difficulty"] is None


def test_get_text_missing_returns_none(temp_db):
    assert db.get_text(999) is None


def test_list_texts_empty(temp_db):
    assert db.list_texts() == []


def test_list_texts_without_attempts(temp_db):
    db.create_text("Uno", "Text one.", 5)
    texts = db.list_texts()
    assert len(texts) == 1
    assert texts[0]["times"] == 0
    assert texts[0]["avg_pronunciation"] is None


def test_list_texts_with_attempts(temp_db):
    text_id = db.create_text("Uno", "Hello world.", 5)
    db.save_attempt(text_id, make_result(pronunciation=80.0))
    db.save_attempt(text_id, make_result(pronunciation=90.0))
    text = db.list_texts()[0]
    assert text["times"] == 2
    assert text["avg_pronunciation"] == 85.0


def test_save_attempt_links_to_text(temp_db):
    text_id = db.create_text("Uno", "Hello world.", 5)
    attempt_id = db.save_attempt(text_id, make_result())
    attempts = db.list_attempts()
    assert len(attempts) == 1
    assert attempts[0]["id"] == attempt_id
    assert attempts[0]["reference_text"] == "Hello world."


def test_update_text(temp_db):
    text_id = db.create_text("Viejo", "Old.", 1)
    db.update_text(text_id, "Nuevo", "New content.", 8)
    text = db.get_text(text_id)
    assert text["title"] == "Nuevo"
    assert text["content"] == "New content."
    assert text["difficulty"] == 8


def test_delete_text_cascades(temp_db):
    text_id = db.create_text("Uno", "Hello world.", 5)
    db.save_attempt(text_id, make_result())
    db.delete_text(text_id)
    assert db.get_text(text_id) is None
    assert db.list_attempts() == []
    # Las palabras del intento tambien se borran.
    assert db.list_word_stats() == []
