"""Utilidades para normalizar y renderizar mensajes del LLM."""

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage


def content_text(message: Any) -> str:
    """Normaliza el `content` de un mensaje del LLM (string o lista de bloques) a string.

    LangChain declara `content` como `str | list[str | dict]`: algunos proveedores (p. ej.
    Gemini con contenido multimodal o en bloques) devuelven una lista de dicts `{"text": ...}`
    en vez de un string. Esta función aplana cualquiera de esas formas a texto plano.
    """
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def render_transcript(messages: Sequence[AnyMessage]) -> str:
    """Renderiza la conversación como texto etiquetado, para pasarla como DATO al revisor.

    Descarta dos cosas que están en el historial pero que nadie dijo en voz alta: los
    `SystemMessage` (las reglas del tutor) y el PRIMER `HumanMessage` (el `session_brief`,
    ver `graph.initial_state`). Los turnos del tutor se etiquetan `Tutor:` en vez de entrar
    como `AIMessage`, justamente para que el revisor no los lea como respuestas propias.
    """
    turns = []
    brief_seen = False
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, HumanMessage) and not brief_seen:
            brief_seen = True
            continue
        label = "Tutor" if isinstance(message, AIMessage) else "Learner"
        turns.append(f"{label}: {content_text(message)}")
    return "\n".join(turns)
