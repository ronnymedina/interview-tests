"""Repositorio del feedback del piloto (tabla `pilot_feedback`).

Aísla el SQL: el endpoint guarda una respuesta llamando `save`, sin escribir SQL a mano.
Recibe el almacenamiento por inyección de dependencia y NO crea la tabla (eso lo hace
`PostgresStorage.init_schema()` o el init del contenedor). Mismo patrón que
`ConversationRepository`. `created_at` lo pone Postgres por DEFAULT now().
"""

from app.feedback.schemas import FeedbackRequest
from app.storage import PostgresStorage


class FeedbackRepository:
    """Inserta respuestas del formulario de feedback. Recibe el almacenamiento inyectado."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    def save(self, user_id: str, feedback: FeedbackRequest) -> int:
        """Inserta una respuesta de feedback y devuelve el id de la fila creada."""
        with self._storage.connect() as conn:
            row = conn.execute(
                "INSERT INTO pilot_feedback "
                "(user_id, liked, rating, comment, wants_more, suggestions) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    user_id,
                    feedback.liked,
                    feedback.rating,
                    feedback.comment,
                    feedback.wants_more,
                    feedback.suggestions,
                ),
            ).fetchone()
            # RETURNING id siempre devuelve la fila recién insertada.
            assert row is not None
            return int(row["id"])
