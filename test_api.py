"""Tests de los endpoints: CRUD de textos y /assess ligado a un texto."""

from conftest import make_result

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
