"""Módulo de conversación: configuración persistida, el grafo de práctica y su orquestación."""

from .graph import (
    FeedbackReport,
    PhraseSuggestion,
    PracticeWord,
    State,
    build_graph,
    initial_state,
)
from .model import ConversationConfig
from .repository import ConversationRepository
from .schemas import AnswerRequest, ConfigRequest, StartRequest
from .service import ConversationError, ConversationService, build_service
from .synthesizer import Synthesizer

__all__ = [
    "AnswerRequest",
    "ConfigRequest",
    "ConversationConfig",
    "ConversationError",
    "ConversationRepository",
    "ConversationService",
    "FeedbackReport",
    "PhraseSuggestion",
    "PracticeWord",
    "StartRequest",
    "State",
    "Synthesizer",
    "build_graph",
    "build_service",
    "initial_state",
]
