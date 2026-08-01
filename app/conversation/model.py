"""Modelo de una configuración de conversación (una fila de `conversation_configs`)."""

from pydantic import BaseModel, ConfigDict


class ConversationConfig(BaseModel):
    """Una configuración de conversación guardada por el cliente."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    user_context: str  # contexto editable del usuario (qué quiere practicar, su CV, etc.)
    created_at: str
    updated_at: str
