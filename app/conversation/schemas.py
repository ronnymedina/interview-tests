"""Esquemas de entrada de la API de conversación, con validación en Pydantic.

La validación vive en las clases (no en `if`s dispersos por los endpoints): los campos se
normalizan y validan con `field_validator` / restricciones de `Field`. Si algo no cumple,
Pydantic lanza `ValidationError` y FastAPI responde 422 automáticamente. Los endpoints
reciben datos ya limpios y confiables.
"""

from pydantic import BaseModel, Field, field_validator


def _stripped_non_empty(value: str, label: str) -> str:
    """Recorta espacios y exige contenido; comparte el mensaje entre esquemas."""
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label} está vacío.")
    return stripped


class StartRequest(BaseModel):
    """Entrada de `POST /conversation/start`.

    Recibe el contexto CRUDO del alumno (un solo campo) más el tope de preguntas. La
    síntesis al brief de dos secciones ocurre por DENTRO del servicio al arrancar; el
    frontend no la ve ni la pide con un endpoint aparte.
    """

    user_context: str
    max_questions: int = Field(default=5, ge=1, le=20)

    @field_validator("user_context")
    @classmethod
    def _user_context_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value, "El contexto")


class AnswerRequest(BaseModel):
    """Entrada de `POST /conversation/answer`: la respuesta transcrita del alumno."""

    conversation_id: str
    text: str

    @field_validator("conversation_id")
    @classmethod
    def _conversation_id_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value, "El id de conversación")

    @field_validator("text")
    @classmethod
    def _text_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value, "La respuesta")


class ConfigRequest(BaseModel):
    """Entrada de crear/editar una configuración de conversación guardada (nombre + contexto)."""

    name: str = Field(max_length=200)
    user_context: str

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value, "El nombre")

    @field_validator("user_context")
    @classmethod
    def _user_context_non_empty(cls, value: str) -> str:
        return _stripped_non_empty(value, "El contexto")
