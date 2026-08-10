"""Construccion de los chat models con init_chat_model, y la config de modelo/temperatura
por rol que la alimenta."""

import pytest

from app.conversation.llm import build_chat_model
from app.conversation.service import ConversationError
from config import settings


def test_build_chat_model_without_api_key_raises_500(monkeypatch):
    """Sin GEMINI_API_KEY, la construccion falla claro (500) en vez de armar el modelo."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(ConversationError) as exc:
        build_chat_model()
    assert exc.value.status == 500


def test_build_chat_model_uses_configured_model_and_key(monkeypatch):
    """Arma el modelo del proveedor+modelo de settings.CHAT_MODEL (sin tocar red)."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key-for-construction")
    monkeypatch.setattr(settings, "CHAT_MODEL", "google_genai:gemini-2.5-flash")
    llm = build_chat_model()
    # init_chat_model resuelve el proveedor google_genai al cliente concreto.
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    assert str(llm.model).endswith("gemini-2.5-flash")


def test_build_chat_model_sin_temperatura_no_la_fija(monkeypatch):
    """Llamado sin argumentos NO le pasa `temperature` al proveedor: la pone él.

    Se espía el kwarg en vez de mirar `llm.temperature` porque el default depende del
    modelo (`gemini-2.5-flash` arranca en 0.7 y `gemini-3.1-flash-lite` en None), y un
    test atado a ese valor pasa o falla segun el CHAT_MODEL del entorno.
    """
    import langchain.chat_models as chat_models

    recibido = {}

    def fake_init_chat_model(model, **kwargs):
        recibido["model"] = model
        recibido["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(chat_models, "init_chat_model", fake_init_chat_model)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key-for-construction")

    build_chat_model()

    assert "temperature" not in recibido["kwargs"]
    assert recibido["model"] == settings.CHAT_MODEL


def test_build_chat_model_fija_la_temperatura_cuando_se_la_dan(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key-for-construction")
    llm = build_chat_model("google_genai:gemini-2.5-flash", 0.2)
    assert llm.temperature == 0.2


def test_build_chat_model_usa_el_modelo_que_se_le_pasa(monkeypatch):
    """El revisor puede correr en otro modelo sin tocar el CHAT_MODEL del tutor."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key-for-construction")
    monkeypatch.setattr(settings, "CHAT_MODEL", "google_genai:gemini-2.5-flash")
    llm = build_chat_model("google_genai:gemini-2.5-pro")
    assert str(llm.model).endswith("gemini-2.5-pro")


def test_review_chat_model_vacio_cae_al_chat_model():
    """El default no cambia el costo: sin tocar el .env, revisor y tutor comparten modelo."""
    assert settings.REVIEW_CHAT_MODEL == ""
    assert (settings.REVIEW_CHAT_MODEL or settings.CHAT_MODEL) == settings.CHAT_MODEL


def test_el_revisor_corre_mas_frio_que_el_tutor():
    """La razón de ser de tener dos instancias: evaluación estable vs preguntas variadas."""
    assert settings.REVIEW_TEMPERATURE < settings.CHAT_TEMPERATURE
