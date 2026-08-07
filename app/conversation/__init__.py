"""Módulo de conversación: el grafo de práctica y su orquestación."""

from .graph import (
    FeedbackReport,
    PhraseSuggestion,
    PracticeWord,
    State,
    build_graph,
    initial_state,
)
from .schemas import StartRequest
from .service import ConversationError, ConversationService, build_service
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
    "build_graph",
    "build_service",
    "initial_state",
]
