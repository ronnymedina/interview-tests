"""Utilidades para normalizar mensajes del LLM."""

from typing import Any


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
