"""Chat model construction and the per-role model/temperature config feeding it.

`build_chat_model` takes model and temperature, and resolves the provider key through
`api_key_for`. What is worth testing here is the translation into a provider instance, and
the key lookup that decides which provider is actually required.
"""

import pytest
from pydantic import ValidationError

from app.conversation import api_key_for, build_chat_model
from app.conversation.service import ConversationError
from config import PROVIDER_API_KEY_FIELDS, Settings, settings

A_MODEL = "google_genai:gemini-2.5-flash"
A_KEY = "fake-key-for-construction"


def test_builds_the_provider_client_for_the_model_string(monkeypatch):
    """`init_chat_model` resolves "google_genai:..." to the concrete client (no network)."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", A_KEY)
    llm = build_chat_model(A_MODEL)
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"
    assert str(llm.model).endswith("gemini-2.5-flash")


def test_without_temperature_it_is_not_sent_to_the_provider(monkeypatch):
    """Called without a temperature, the kwarg must be absent, not None.

    The kwarg is spied instead of reading `llm.temperature` because the default depends on
    the model (`gemini-2.5-flash` starts at 0.7, `gemini-3.1-flash-lite` at None), and a
    test pinned to that value passes or fails depending on the environment's CHAT_MODEL.
    """
    import langchain.chat_models as chat_models

    monkeypatch.setattr(settings, "GEMINI_API_KEY", A_KEY)
    received = {}

    def fake_init_chat_model(model, **kwargs):
        received["model"] = model
        received["kwargs"] = kwargs
        return object()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chat_models, "init_chat_model", fake_init_chat_model)
        build_chat_model(A_MODEL)

    assert "temperature" not in received["kwargs"]
    assert received["model"] == A_MODEL


def test_the_temperature_is_applied_when_given(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", A_KEY)
    llm = build_chat_model(A_MODEL, 0.2)
    assert llm.temperature == 0.2


def test_api_key_for_returns_the_key_of_the_models_provider(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", A_KEY)
    assert api_key_for(A_MODEL) == A_KEY


def test_a_missing_key_for_the_required_provider_raises_500(monkeypatch):
    """Only the provider the model names is required; without its key, build fails clearly."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(ConversationError) as exc:
        api_key_for(A_MODEL)
    assert exc.value.status == 500
    assert "GEMINI_API_KEY" in str(exc.value)


def test_every_supported_provider_has_its_key_field_declared():
    """The map is the contract: a provider whose key field does not exist would blow up
    with an AttributeError at startup instead of a clear message."""
    for field in PROVIDER_API_KEY_FIELDS.values():
        assert field in Settings.model_fields


def test_an_unsupported_provider_is_rejected_at_config_time():
    """Wrong provider fails when Settings is built, not on the first request."""
    with pytest.raises(ValidationError, match="unsupported provider"):
        Settings(CHAT_MODEL="anthropic:claude-opus-4")


def test_a_model_string_without_provider_is_rejected():
    with pytest.raises(ValidationError, match="expected 'provider:model'"):
        Settings(CHAT_MODEL="gemini-2.5-flash")


def test_an_empty_review_model_is_accepted_and_falls_back():
    """The default costs nothing extra: untouched, reviewer and tutor share the model."""
    assert settings.REVIEW_CHAT_MODEL == ""
    assert Settings(REVIEW_CHAT_MODEL="").REVIEW_CHAT_MODEL == ""


def test_an_empty_chat_model_is_rejected():
    """Unlike the reviewer's, this one has nothing to fall back to: empty must fail at
    startup instead of reaching the builder and blowing up on a provider lookup."""
    with pytest.raises(ValidationError, match="cannot be empty"):
        Settings(CHAT_MODEL="")


def test_the_reviewer_runs_colder_than_the_tutor():
    """Why two instances exist at all: stable evaluation vs varied questions."""
    assert settings.REVIEW_TEMPERATURE < settings.CHAT_TEMPERATURE
