"""Módulo de conversación: el grafo de práctica y su orquestación."""

from typing import Any

from config import PROVIDER_API_KEY_FIELDS, settings

from .graph import (
    ConversationGraph,
    FeedbackReport,
    PhraseSuggestion,
    PracticeWord,
    State,
    initial_state,
)
from .schemas import StartRequest
from .service import ConversationError, ConversationService
from .synthesizer import Synthesizer

__all__ = [
    "ConversationError",
    "ConversationGraph",
    "ConversationService",
    "FeedbackReport",
    "PhraseSuggestion",
    "PracticeWord",
    "StartRequest",
    "State",
    "Synthesizer",
    "build_chat_model",
    "build_conversation_graph_service",
    "initial_state",
]


def api_key_for(model: str) -> str:
    """Return the configured API key for the provider named by a "provider:model" string.

    Only the provider the caller actually needs is required. Running the reviewer on a
    second provider must not start demanding a key for one nothing uses — hence the lookup
    per model instead of a single global check.
    """
    provider = model.partition(":")[0]
    # The field name is guaranteed by the validator in `config.py`, which rejects unknown
    # providers before a Settings instance exists.
    key = getattr(settings, PROVIDER_API_KEY_FIELDS[provider])
    if not key:
        raise ConversationError(
            f"Falta {PROVIDER_API_KEY_FIELDS[provider]} en el archivo .env, y el modelo "
            f"{model!r} la necesita. Copia .env.example a .env y pon tu clave.",
            status=500,
        )
    return str(key)


def build_chat_model(model: str, api_key: str, temperature: float | None = None):
    """Translate a "provider:model" string into a LangChain chat model instance.

    The only point in the module that knows about concrete providers. It reads no
    configuration: model, key and temperature all come from the caller, so the composition
    root below stays the single place where `settings` is consulted.
    """
    from langchain.chat_models import init_chat_model

    # `temperature=None` is not passed through: some providers send it literally in the
    # request instead of reading it as "unspecified". When unset, the key is simply absent.
    kwargs: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
    return init_chat_model(model, api_key=api_key, **kwargs)


def build_conversation_graph_service(checkpointer=None) -> ConversationService:
    """Composition root: arma los tres chat models → el grafo → el sintetizador.

    Se llama UNA vez en el arranque. Tres roles, tres instancias: el tutor corre caliente
    (preguntas variadas), el revisor frío (evaluación estable) y el sintetizador deja la
    temperatura al default del proveedor, que es su comportamiento histórico.
    `REVIEW_CHAT_MODEL` vacío cae a `CHAT_MODEL`, así que por default los tres apuntan al
    mismo modelo y el costo por token no cambia.
    """
    model = settings.CHAT_MODEL
    review_model = settings.REVIEW_CHAT_MODEL or model
    chat_key = api_key_for(settings.CHAT_MODEL)
    review_key = api_key_for(review_model)

    synthesizer_llm = build_chat_model(model, chat_key)
    tutor_llm = build_chat_model(model, chat_key, settings.CHAT_TEMPERATURE)
    review_llm = build_chat_model(review_model, review_key, settings.REVIEW_TEMPERATURE)
    return ConversationService(
        ConversationGraph(tutor_llm, review_llm, checkpointer).compile(),
        Synthesizer(synthesizer_llm),
    )
