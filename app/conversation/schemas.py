"""Esquema de entrada de la API de conversación, con validación en Pydantic.

La validación vive en la clase (no en `if`s dispersos por los endpoints): los campos se
normalizan y validan con `field_validator` / restricciones de `Field`. Si algo no cumple,
Pydantic lanza `ValidationError` y FastAPI responde 422 automáticamente. El endpoint
recibe datos ya limpios y confiables.

`POST /conversation/answer` no tiene esquema: recibe multipart (audio + transcript) y
valida sus campos inline.
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
