"""Tests del modulo nuevo app/conversation: construccion del LLM con init_chat_model."""

import pytest

from app.conversation.service import ConversationError, build_llm
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
