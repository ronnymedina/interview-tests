"""Módulo de conversación: el grafo de práctica y su orquestación."""

from config import settings

from .graph import (
    FeedbackReport,
    PhraseSuggestion,
    PracticeWord,
    State,
    build_graph,
    initial_state,
)
from .llm import build_chat_model
from .schemas import StartRequest
from .service import ConversationError, ConversationService
from .synthesizer import Synthesizer

__all__ = [
    "ConversationError",
    "ConversationService",
    "FeedbackReport",
    "PhraseSuggestion",
    "PracticeWord",
    "StartRequest",
    "State",
    "Synthesizer",
    "build_chat_model",
    "build_conversation_graph_service",
    "build_graph",
    "initial_state",
]


def build_conversation_graph_service(checkpointer=None) -> ConversationService:
    """Composition root: arma los tres chat models → el grafo → el sintetizador.

    Se llama UNA vez en el arranque. Tres roles, tres instancias: el sintetizador conserva
    el comportamiento histórico (`build_chat_model()` pelado), el tutor corre caliente y el
    revisor frío. `REVIEW_CHAT_MODEL` vacío cae a `CHAT_MODEL`, así que por default los tres
    apuntan al mismo modelo y el costo por token no cambia.
    """
    synthesizer_llm = build_chat_model()
    tutor_llm = build_chat_model(settings.CHAT_MODEL, settings.CHAT_TEMPERATURE)
    review_llm = build_chat_model(
        settings.REVIEW_CHAT_MODEL or settings.CHAT_MODEL, settings.REVIEW_TEMPERATURE
    )
    return ConversationService(
        build_graph(tutor_llm, review_llm, checkpointer), Synthesizer(synthesizer_llm)
    )
