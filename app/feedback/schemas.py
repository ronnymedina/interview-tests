"""Esquema de entrada del formulario de feedback del piloto, validado con Pydantic.

Todos los campos son opcionales (el usuario puede dejar partes sin llenar). La única regla
es que `rating`, si viene, esté en 1..5; fuera de rango, Pydantic lanza ValidationError y
FastAPI responde 422. Refleja la tabla `pilot_feedback` (columnas anulables salvo los TEXT).
"""

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """Formulario de feedback: like/dislike, estrellas 1–5, comentario y '¿más funciones?'."""

    liked: bool | None = None  # like / dislike
    rating: int | None = Field(default=None, ge=1, le=5)  # estrellas 1..5
    comment: str = ""
    wants_more: bool | None = None  # ¿te interesarían más funciones?
    suggestions: str = ""  # cuáles
