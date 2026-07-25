"""Tests de los endpoints: CRUD de textos y /assess ligado a un texto."""

from conftest import make_result, make_unscripted_result

import conversation
import db
import speech


def test_create_and_list_text(client):
    resp = client.post("/texts", json={"title": "Saludo", "content": "Hello.", "difficulty": 4})
    assert resp.status_code == 200
    created = resp.json()
    assert created["title"] == "Saludo"

    listed = client.get("/texts").json()
    assert len(listed) == 1
    assert listed[0]["times"] == 0
    assert listed[0]["avg_pronunciation"] is None


def test_create_text_without_difficulty(client):
    resp = client.post("/texts", json={"title": "Sin nivel", "content": "Text.", "difficulty": None})
    assert resp.status_code == 200
    assert resp.json()["difficulty"] is None


def test_create_text_empty_title_is_rejected(client):
    resp = client.post("/texts", json={"title": "  ", "content": "Text.", "difficulty": None})
    assert resp.status_code == 400


def test_create_text_empty_content_is_rejected(client):
    resp = client.post("/texts", json={"title": "Titulo", "content": "  ", "difficulty": None})
    assert resp.status_code == 400


def test_create_text_difficulty_out_of_range_is_rejected(client):
    resp = client.post("/texts", json={"title": "Titulo", "content": "Text.", "difficulty": 11})
    assert resp.status_code == 400


def test_update_text(client):
    text_id = client.post(
        "/texts", json={"title": "Viejo", "content": "Old.", "difficulty": 1}
    ).json()["id"]
    resp = client.put(
        f"/texts/{text_id}", json={"title": "Nuevo", "content": "New.", "difficulty": 9}
    )
    assert resp.status_code == 200
    assert db.get_text(text_id)["title"] == "Nuevo"


def test_delete_text(client):
    text_id = client.post(
        "/texts", json={"title": "Uno", "content": "Hello.", "difficulty": 5}
    ).json()["id"]
    assert client.delete(f"/texts/{text_id}").status_code == 200
    assert client.get("/texts").json() == []


def test_assess_with_missing_text_returns_404(client):
    resp = client.post(
        "/assess",
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
        data={"text_id": "999"},
    )
    assert resp.status_code == 404


def test_assess_saves_attempt_linked_to_text(client, monkeypatch):
    text_id = client.post(
        "/texts", json={"title": "Uno", "content": "Hello world.", "difficulty": 5}
    ).json()["id"]

    monkeypatch.setattr(speech, "assess", lambda wav_path, reference_text: make_result())

    resp = client.post(
        "/assess",
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
        data={"text_id": str(text_id)},
    )
    assert resp.status_code == 200
    assert resp.json()["attempt_id"]

    text = client.get("/texts").json()[0]
    assert text["times"] == 1


def test_conversation_start_returns_question(client, monkeypatch):
    monkeypatch.setattr(conversation, "start", lambda prompt, max_q: ("cid-1", "First question?"))
    resp = client.post("/conversation/start", json={"system_prompt": "Roleplay", "max_questions": 3})
    assert resp.status_code == 200
    assert resp.json() == {"conversation_id": "cid-1", "question": "First question?"}


def test_conversation_start_empty_prompt_rejected(client):
    resp = client.post("/conversation/start", json={"system_prompt": "   ", "max_questions": 3})
    assert resp.status_code == 400


def test_conversation_start_bad_max_rejected(client):
    resp = client.post("/conversation/start", json={"system_prompt": "Roleplay", "max_questions": 0})
    assert resp.status_code == 400


def test_conversation_answer_azure_shows_turn_scores(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    monkeypatch.setattr(conversation, "answer", lambda cid, text: {"question": "Next question?"})
    resp = client.post(
        "/conversation/cid-1/answer",
        data={"mode": "azure"},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_question"] == "Next question?"
    assert body["recognized_text"] == "hello world"
    # En modo azure el score del turno esta presente.
    assert body["turn_scores"]["pronunciation"] == 85.0


def test_conversation_answer_browser_defers_scoring(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    monkeypatch.setattr(conversation, "answer", lambda cid, text: {"question": "Next?"})
    resp = client.post(
        "/conversation/cid-1/answer",
        data={"mode": "browser", "transcript": "I went to work"},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_question"] == "Next?"
    # El texto viene del cliente; no hay score por turno (diferido).
    assert body["recognized_text"] == "I went to work"
    assert body["turn_scores"] is None


def test_conversation_answer_browser_without_transcript_rejected(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    resp = client.post(
        "/conversation/cid-1/answer",
        data={"mode": "browser", "transcript": "   "},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 400


def test_conversation_answer_final_aggregates_and_saves(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    final_payload = {
        "final": {
            "content_feedback": "Buen intento.",
            "system_prompt": "Roleplay",
            "questions_asked": 1,
        }
    }
    monkeypatch.setattr(conversation, "answer", lambda cid, text: final_payload)

    resp = client.post(
        "/conversation/cid-final/answer",
        data={"mode": "azure"},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final"]["content_feedback"] == "Buen intento."
    # Los scores del final salen del agregado del scoring encolado.
    assert body["final"]["scores"]["pronunciation"] == 85.0

    saved = db.list_conversations()
    assert len(saved) == 1
    assert saved[0]["system_prompt"] == "Roleplay"
    assert saved[0]["pronunciation_score"] == 85.0
    # Las palabras del scoring alimentaron el banco.
    assert [s["word"] for s in db.list_word_stats()] == ["hello"]


def test_conversation_answer_unknown_id_returns_404(client, monkeypatch):
    # exists() debe cortar ANTES de gastar la llamada paga a Azure: si assess_unscripted
    # llegara a invocarse igual lo dejamos pasar de forma defensiva, pero lo que probamos
    # es que la respuesta es 404 sin depender de su resultado.
    monkeypatch.setattr(conversation, "exists", lambda cid: False)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())

    resp = client.post(
        "/conversation/does-not-exist/answer",
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 404
