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


def test_save_and_list_conversation(temp_db):
    scores = {"pronunciation": 82.0, "accuracy": 85.0, "fluency": 80.0, "prosody": 78.0}
    words = [
        {"word": "Yesterday", "error_type": "None", "accuracy": 90.0, "phonemes": []},
        {"word": "worked", "error_type": "Mispronunciation", "accuracy": 55.0, "phonemes": []},
    ]
    cid = db.save_conversation("Roleplay sobre trabajo", 3, scores, "Buen vocabulario.", words)
    listed = db.list_conversations()
    assert len(listed) == 1
    assert listed[0]["id"] == cid
    assert listed[0]["system_prompt"] == "Roleplay sobre trabajo"
    assert listed[0]["questions_asked"] == 3
    assert listed[0]["pronunciation_score"] == 82.0
    assert listed[0]["content_feedback"] == "Buen vocabulario."


def test_conversation_words_feed_word_bank(temp_db):
    scores = {"pronunciation": 82.0, "accuracy": 85.0, "fluency": 80.0, "prosody": 78.0}
    words = [{"word": "Yesterday", "error_type": "None", "accuracy": 90.0, "phonemes": []}]
    db.save_conversation("Roleplay", 1, scores, "ok", words)
    stats = db.list_word_stats()
    assert [s["word"] for s in stats] == ["yesterday"]
    assert stats[0]["avg_accuracy"] == 90.0


def test_conversation_prompt_crud(temp_db):
    assert db.list_conversation_prompts() == []

    pid = db.create_conversation_prompt("Entrevista", "Ask about work.")
    assert isinstance(pid, int) and pid > 0

    got = db.get_conversation_prompt(pid)
    assert got["name"] == "Entrevista"
    assert got["system_prompt"] == "Ask about work."
    assert got["created_at"] and got["updated_at"]

    db.update_conversation_prompt(pid, "Entrevista v2", "Ask about backend work.")
    got = db.get_conversation_prompt(pid)
    assert got["name"] == "Entrevista v2"
    assert got["system_prompt"] == "Ask about backend work."

    db.delete_conversation_prompt(pid)
    assert db.get_conversation_prompt(pid) is None
    assert db.list_conversation_prompts() == []


def test_conversation_prompts_ordered_id_desc(temp_db):
    first = db.create_conversation_prompt("Uno", "A")
    second = db.create_conversation_prompt("Dos", "B")
    ids = [p["id"] for p in db.list_conversation_prompts()]
    assert ids == [second, first]
