"""Tests del modulo nuevo app/conversation: construccion del LLM con init_chat_model."""

from types import SimpleNamespace

import pytest

from app.conversation.service import ConversationError, ConversationService, build_llm
from config import settings


def test_build_llm_without_api_key_raises_500(monkeypatch):
    """Sin GEMINI_API_KEY, build_llm falla claro (500) en vez de construir el modelo."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(ConversationError) as exc:
        build_llm()
    assert exc.value.status == 500


def test_build_llm_uses_configured_model_and_key(monkeypatch):
    """build_llm arma el modelo del proveedor+modelo de settings.CHAT_MODEL (sin tocar red)."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key-for-construction")
    monkeypatch.setattr(settings, "CHAT_MODEL", "google_genai:gemini-2.5-flash")
    llm = build_llm()
    # init_chat_model resuelve el proveedor google_genai al cliente concreto.
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    assert str(llm.model).endswith("gemini-2.5-flash")


class FakeGraph:
    """Doble del grafo compilado: solo lo que `ConversationService` le pide.

    `get_state().values` es el estado ANTES del turno (todavía sin terminar, porque si no
    `answer` corta con 409), e `invoke` devuelve el estado ya actualizado. Acá se testea el
    contrato del servicio hacia el endpoint, no el grafo.
    """

    def __init__(self, values: dict) -> None:
        self._values = values

    def get_state(self, config):
        return SimpleNamespace(values={**self._values, "finished": False})

    def invoke(self, payload, config=None):
        return self._values


def test_answer_final_devuelve_el_session_brief():
    """La clave del payload es `session_brief`, no `brief`: es la única superficie
    pública del rename."""
    graph = FakeGraph(
        {
            "finished": True,
            "content_feedback": "Muy bien el pasado simple.",
            "session_brief": "### Puntos\n- Pasado simple\n\n### Contexto\nMi CV",
            "questions_asked": 5,
            "max_questions": 5,
            "practice_words": [],
            "practice_phrases": [],
        }
    )
    service = ConversationService(graph, synthesizer=None)

    result = service.answer("abc123", "I worked on a payments API")

    assert result["final"]["session_brief"].startswith("### Puntos")
    assert "brief" not in result["final"]
